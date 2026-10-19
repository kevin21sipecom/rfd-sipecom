"""Puente con Engram: publica los RFD terminados para el estimador de horas (generador-tiempos).

Engram (`engram serve`, http://127.0.0.1:7437) hace de buzón compartido entre las dos aplicaciones:

- el creador deja una observación `handoff` por código de RFD; usa `topic_key`, de modo que una versión nueva
  reemplaza a la anterior en lugar de duplicarla;
- el estimador la lee, descarga el Word desde este servidor y deja una observación `estimacion` con las horas.

El contenido de cada observación es un resumen legible seguido de un bloque ```json con la carga completa.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode, urlparse

ENGRAM_URL = os.environ.get("ENGRAM_URL", "http://127.0.0.1:7437").rstrip("/")
ESTIMADOR_URL = os.environ.get("ESTIMADOR_URL", "http://127.0.0.1:8000").rstrip("/")
PROYECTO = "rfd-pipeline"
SESION = "rfd-pipeline"
HANDOFF = "handoff"
ESTIMACION = "estimacion"
# Cada RFD deja 2 observaciones (envío y estimación): 1000 cubren unos 500 RFD sin perder el estado de los antiguos.
LIMITE_ESTADO = 1000


class EngramNoDisponible(RuntimeError):
    pass


def _pedir(metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None, timeout: float = 5) -> Any:
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8") if cuerpo is not None else None
    req = urllib.request.Request(ENGRAM_URL + ruta, data=datos, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raise EngramNoDisponible(f"Engram respondió {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from e
    except (urllib.error.URLError, OSError) as e:
        raise EngramNoDisponible(f"Engram no responde en {ENGRAM_URL}. Inicie `engram serve`.") from e


def disponible() -> bool:
    try:
        return (_pedir("GET", "/health", timeout=2) or {}).get("status") == "ok"
    except EngramNoDisponible:
        return False


def asegurar_servidor(espera: float = 6.0) -> bool:
    """Si Engram no responde en una dirección local, lanza `engram serve <puerto>` en segundo plano.
    ENGRAM_AUTOSTART=0 lo desactiva."""
    if disponible():
        return True
    url = urlparse(ENGRAM_URL)
    exe = shutil.which("engram")
    if os.environ.get("ENGRAM_AUTOSTART", "1") == "0" or not exe or url.hostname not in ("127.0.0.1", "localhost"):
        return False
    windows = sys.platform == "win32"
    subprocess.Popen(
        [exe, "serve", str(url.port or 7437)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if windows else 0,
        start_new_session=not windows,
    )
    limite = time.time() + espera
    while time.time() < limite:
        if disponible():
            return True
        time.sleep(0.25)
    return False


def contenido(resumen: str, carga: dict[str, Any]) -> str:
    return f"{resumen}\n\n```json\n{json.dumps(carga, ensure_ascii=False, indent=2)}\n```"


def leer_carga(texto: str) -> dict[str, Any] | None:
    m = re.search(r"```json\s*(\{.*\})\s*```", texto or "", re.S)
    if not m:
        return None
    try:
        carga = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return carga if isinstance(carga, dict) else None


def clave(codigo: str) -> str:
    return re.sub(r"[^\w.-]+", "-", codigo.strip().lower()).strip("-")


def _guardar(tipo: str, titulo: str, topic: str, texto: str) -> int:
    _pedir("POST", "/sessions", {"id": SESION, "project": PROYECTO, "directory": ""})
    r = _pedir("POST", "/observations", {"session_id": SESION, "project": PROYECTO, "scope": "project", "type": tipo,
                                         "title": titulo, "topic_key": topic, "content": texto})
    return int(r["id"])


def publicar_rfd(carga: dict[str, Any]) -> int:
    """Deja el RFD en el buzón del estimador. Devuelve el id de la observación en Engram."""
    resumen = (
        f"**RFD listo para estimar**: {carga['codigo']} v{carga['version']} · {carga['cliente']}\n"
        f"**Título**: {carga['titulo']}\n"
        f"**Requerimientos**: {len(carga.get('requerimientos', []))}\n"
        f"**Word**: {carga['url_docx']}"
    )
    return _guardar(HANDOFF, f"RFD listo para estimar: {carga['codigo']} v{carga['version']}",
                    f"rfd-handoff/{clave(carga['codigo'])}", contenido(resumen, carga))


def mensajes(tipo: str | None = None, limite: int = 100) -> list[dict[str, Any]]:
    """Observaciones del puente (las más recientes primero), con su carga JSON y los metadatos de Engram."""
    obs = _pedir("GET", "/observations/recent?" + urlencode({"project": PROYECTO, "limit": limite})) or []
    salida = []
    for o in obs:
        if tipo and o.get("type") != tipo:
            continue
        carga = leer_carga(o.get("content", ""))
        if carga is not None:
            salida.append({**carga, "observacion_id": o["id"], "tipo_observacion": o.get("type"),
                           "actualizado": o.get("updated_at", ""), "revisiones": o.get("revision_count", 1)})
    return sorted(salida, key=lambda m: m["actualizado"], reverse=True)


def estado(codigo: str) -> dict[str, Any]:
    """Último envío y última estimación registrados para un código de RFD."""
    k = clave(codigo)
    propios = [m for m in mensajes(limite=LIMITE_ESTADO) if clave(m.get("codigo", "")) == k]
    return {
        "handoff": next((m for m in propios if m["tipo_observacion"] == HANDOFF), None),
        "estimacion": next((m for m in propios if m["tipo_observacion"] == ESTIMACION), None),
    }
