"""Puente con el estimador vía Engram: se prueba contra un Engram falso en memoria (mismo contrato HTTP)."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from generador_rfd import engram


class EngramFalso(BaseHTTPRequestHandler):
    obs: list[dict] = []

    def log_message(self, *a):  # silencio en la salida de pytest
        pass

    def _json(self, codigo: int, cuerpo) -> None:
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/health":
            return self._json(200, {"status": "ok"})
        if u.path == "/observations/recent":
            q = parse_qs(u.query)
            filas = [o for o in self.obs if o["project"] == q["project"][0]][::-1][: int(q.get("limit", ["1000"])[0])]
            return self._json(200, filas or None)
        m = re.fullmatch(r"/observations/(\d+)", u.path)
        if m:
            o = next((o for o in self.obs if o["id"] == int(m.group(1))), None)
            return self._json(200 if o else 404, o or {"error": "not found"})
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/sessions":
            return self._json(200, {"id": cuerpo["id"], "status": "created"})
        previa = next((o for o in self.obs if cuerpo.get("topic_key") and o["topic_key"] == cuerpo["topic_key"].lower()), None)
        if previa:
            previa.update(content=cuerpo["content"], title=cuerpo["title"], revision_count=previa["revision_count"] + 1)
            return self._json(200, {"id": previa["id"], "status": "saved"})
        o = {"id": len(self.obs) + 1, "type": cuerpo["type"], "title": cuerpo["title"], "content": cuerpo["content"],
             "project": cuerpo["project"], "topic_key": cuerpo.get("topic_key", "").lower(), "revision_count": 1,
             "updated_at": f"2026-10-14 10:00:{len(self.obs):02d}"}
        self.obs.append(o)
        self._json(200, {"id": o["id"], "status": "saved"})


@pytest.fixture
def engram_falso(monkeypatch):
    EngramFalso.obs = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), EngramFalso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(engram, "ENGRAM_URL", f"http://127.0.0.1:{srv.server_port}")
    yield EngramFalso.obs
    srv.shutdown()


def _carga(version: str = "0.1") -> dict:
    return {"codigo": "RFD 042", "cliente": "Banco X", "titulo": "Pagos", "version": version,
            "requerimientos": [{"id": "RF-01", "nombre": "Pagar"}], "url_docx": "http://127.0.0.1:2122/api/rfds/7/archivo/docx",
            "enviado": "2026-10-14T10:00:00"}


def test_leer_carga_extrae_el_bloque_json():
    texto = engram.contenido("**Resumen**", {"a": 1, "b": "ñ"})
    assert engram.leer_carga(texto) == {"a": 1, "b": "ñ"}
    assert engram.leer_carga("sin bloque") is None


def test_una_version_nueva_reemplaza_el_envio_anterior(engram_falso):
    id1 = engram.publicar_rfd(_carga("0.1"))
    id2 = engram.publicar_rfd(_carga("0.2"))
    assert id1 == id2 and len(engram_falso) == 1
    assert engram_falso[0]["topic_key"] == "rfd-handoff/rfd-042"
    assert engram.estado("rfd 042")["handoff"]["version"] == "0.2"


def test_estado_devuelve_la_estimacion_del_mismo_codigo(engram_falso):
    engram.publicar_rfd(_carga())
    carga = {"codigo": "RFD 042", "version": "0.1", "total_horas_proyecto": 120.0, "total_horas_dev": 60.0}
    engram._guardar(engram.ESTIMACION, "Estimación", "rfd-estimacion/rfd-042", engram.contenido("", carga))
    e = engram.estado("RFD 042")
    assert e["estimacion"]["total_horas_proyecto"] == 120.0
    assert engram.estado("OTRO")["handoff"] is None


def test_sin_engram_lanza_error_claro(monkeypatch):
    monkeypatch.setattr(engram, "ENGRAM_URL", "http://127.0.0.1:9")
    assert not engram.disponible()
    with pytest.raises(engram.EngramNoDisponible, match="engram serve"):
        engram.publicar_rfd(_carga())


def test_endpoint_envia_el_rfd_con_url_de_descarga(engram_falso, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from generador_rfd import servidor

    docx = tmp_path / "RFD_042.docx"
    docx.write_bytes(b"PK")

    class AlmacenFalso:
        def obtener(self, rfd_id):
            return {"codigo": "RFD 042", "cliente": "Banco X", "titulo": "Pagos", "version": "0.3", "ruta_docx": str(docx),
                    "datos": {"objetivo": "Pagar", "requerimientos": [{"id": "RF-01", "nombre": "Pagar"}]}}

    monkeypatch.setattr(servidor, "almacen", lambda: AlmacenFalso())
    r = TestClient(servidor.app).post("/api/rfds/7/enviar-estimador", json={"proyecto": "C:/repos/x"})
    assert r.status_code == 200, r.text
    carga = engram.leer_carga(engram_falso[0]["content"])
    assert carga["url_docx"] == "http://testserver/api/rfds/7/archivo/docx"
    assert carga["proyecto"] == "C:/repos/x" and carga["version"] == "0.3"


def test_estado_de_un_rfd_antiguo_sobrevive_a_muchos_envios(engram_falso):
    engram.publicar_rfd(_carga())
    for i in range(150):
        engram.publicar_rfd({**_carga(), "codigo": f"RFD {i + 100}"})
    assert engram.estado("RFD 042")["handoff"]["version"] == "0.1"


def test_endpoint_responde_503_si_engram_no_esta_activo(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from generador_rfd import servidor

    docx = tmp_path / "RFD_042.docx"
    docx.write_bytes(b"PK")

    class AlmacenFalso:
        def obtener(self, rfd_id):
            return {"codigo": "RFD 042", "cliente": "X", "titulo": "T", "version": "0.1", "ruta_docx": str(docx),
                    "datos": {"requerimientos": []}}

    monkeypatch.setattr(servidor, "almacen", lambda: AlmacenFalso())
    monkeypatch.setattr(engram, "ENGRAM_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ENGRAM_AUTOSTART", "0")
    r = TestClient(servidor.app).post("/api/rfds/7/enviar-estimador", json={})
    assert r.status_code == 503
