"""Historial persistente de RFD en SQLite: versiones, preguntas para el cliente y sus respuestas.

Cada generación o mejora registra una fila en `rfds` (con el JSON completo del RFD) y sus preguntas
en `preguntas`. Las respuestas se guardan a medida que se escriben, de modo que «Mejorar RFD» sólo
necesita elegir el RFD del historial: no hay que volver a cargar archivos.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .reglas import Regla, validar_regla
from .schema import normalizar, validar_estructura

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS rfds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL,
    cliente TEXT NOT NULL,
    titulo TEXT NOT NULL,
    version TEXT NOT NULL,
    padre_id INTEGER REFERENCES rfds(id),
    creado TEXT NOT NULL,
    origen TEXT NOT NULL,              -- generado | mejorado | importado
    proveedor TEXT, modelo TEXT,
    datos_json TEXT NOT NULL,
    analisis_json TEXT,
    calidad_json TEXT, uso_json TEXT, hallazgos_json TEXT,
    ruta_docx TEXT, ruta_pdf TEXT, ruta_cuestionario TEXT
);
CREATE INDEX IF NOT EXISTS rfds_codigo ON rfds(codigo);
CREATE UNIQUE INDEX IF NOT EXISTS rfds_docx ON rfds(ruta_docx);
CREATE TABLE IF NOT EXISTS preguntas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfd_id INTEGER NOT NULL REFERENCES rfds(id) ON DELETE CASCADE,
    pid TEXT NOT NULL,
    tema TEXT NOT NULL, contexto TEXT NOT NULL, pregunta TEXT NOT NULL, relacion_json TEXT NOT NULL,
    respuesta TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'abierta',  -- abierta | respondida | pendiente
    respondida_en TEXT,
    UNIQUE (rfd_id, pid)
);
CREATE TABLE IF NOT EXISTS reglas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,                     -- evitar | exigir
    texto TEXT NOT NULL,
    seccion TEXT NOT NULL DEFAULT 'todo',
    patron TEXT NOT NULL DEFAULT '',        -- verificación automática opcional (términos con | o re:…)
    cliente TEXT NOT NULL DEFAULT '',       -- vacío: todos los clientes
    activa INTEGER NOT NULL DEFAULT 1,
    creada TEXT NOT NULL,
    actualizada TEXT NOT NULL
);
"""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Almacen:
    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()
        with self._conexion() as c:
            c.executescript(ESQUEMA_SQL)

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        with self._candado:
            c = sqlite3.connect(self.ruta)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            try:
                yield c
                c.commit()
            finally:
                c.close()

    # ------------------------------------------------------------------ escritura
    def registrar(self, datos: dict[str, Any], *, origen: str, ruta_docx: Path | None = None, padre_id: int | None = None,
                  proveedor: str = "", modelo: str = "", analisis: dict | None = None, calidad: dict | None = None,
                  uso: dict | None = None, hallazgos: list[dict] | None = None, ruta_pdf: str | None = None) -> int:
        normalizar(datos)
        cuestionario = ruta_docx.with_suffix(".cuestionario.docx") if ruta_docx else None
        with self._conexion() as c:
            if ruta_docx is not None:
                previo = c.execute("SELECT id FROM rfds WHERE ruta_docx = ?", (str(ruta_docx),)).fetchone()
                if previo:  # el mismo archivo regenerado reemplaza su registro
                    c.execute("UPDATE rfds SET padre_id = NULL WHERE padre_id = ?", (previo["id"],))
                    c.execute("DELETE FROM rfds WHERE id = ?", (previo["id"],))
            cur = c.execute(
                """INSERT INTO rfds (codigo, cliente, titulo, version, padre_id, creado, origen, proveedor, modelo, datos_json,
                   analisis_json, calidad_json, uso_json, hallazgos_json, ruta_docx, ruta_pdf, ruta_cuestionario)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (datos["codigo"], datos["cliente"], datos["titulo"], datos.get("version", "0.1"), padre_id, _ahora(), origen,
                 proveedor, modelo, json.dumps(datos, ensure_ascii=False),
                 json.dumps(analisis, ensure_ascii=False) if analisis else None,
                 json.dumps(calidad, ensure_ascii=False) if calidad else None,
                 json.dumps(uso, ensure_ascii=False) if uso else None,
                 json.dumps(hallazgos or [], ensure_ascii=False),
                 str(ruta_docx) if ruta_docx else None, ruta_pdf,
                 str(cuestionario) if cuestionario and cuestionario.is_file() else None),
            )
            rfd_id = int(cur.lastrowid)
            c.executemany(
                "INSERT INTO preguntas (rfd_id, pid, tema, contexto, pregunta, relacion_json) VALUES (?, ?, ?, ?, ?, ?)",
                [(rfd_id, p["id"], p["tema"], p["contexto"], p["pregunta"], json.dumps(p.get("relacion", []), ensure_ascii=False))
                 for p in datos.get("preguntas_cliente", [])],
            )
        return rfd_id

    def responder(self, rfd_id: int, pid: str, respuesta: str) -> dict[str, Any]:
        texto = respuesta.strip()
        estado = "pendiente" if texto.lower().rstrip(".") in ("pendiente", "por confirmar") else ("respondida" if texto else "abierta")
        with self._conexion() as c:
            cur = c.execute(
                "UPDATE preguntas SET respuesta = ?, estado = ?, respondida_en = ? WHERE rfd_id = ? AND pid = ?",
                (texto, estado, _ahora() if texto else None, rfd_id, pid),
            )
            if cur.rowcount == 0:
                raise KeyError(f"La pregunta {pid} no existe en el RFD {rfd_id}.")
        return {"pid": pid, "respuesta": texto, "estado": estado}

    def responder_varias(self, rfd_id: int, respuestas: dict[str, str]) -> int:
        conocidas = {p["pid"] for p in self.preguntas(rfd_id)}
        n = 0
        for pid, texto in respuestas.items():
            if pid in conocidas:
                self.responder(rfd_id, pid, texto)
                n += 1
        return n

    def eliminar(self, rfd_id: int) -> None:
        with self._conexion() as c:
            c.execute("UPDATE rfds SET padre_id = NULL WHERE padre_id = ?", (rfd_id,))
            c.execute("DELETE FROM rfds WHERE id = ?", (rfd_id,))

    # ------------------------------------------------------------------ lectura
    def listar(self) -> list[dict[str, Any]]:
        with self._conexion() as c:
            filas = c.execute(
                """SELECT r.id, r.codigo, r.cliente, r.titulo, r.version, r.padre_id, r.creado, r.origen, r.proveedor, r.modelo,
                          r.calidad_json, r.ruta_docx,
                          SUM(CASE WHEN p.estado = 'abierta' THEN 1 ELSE 0 END) AS abiertas,
                          SUM(CASE WHEN p.estado = 'respondida' THEN 1 ELSE 0 END) AS respondidas,
                          COUNT(p.id) AS preguntas,
                          (SELECT COUNT(*) FROM rfds h WHERE h.padre_id = r.id) AS hijos
                   FROM rfds r LEFT JOIN preguntas p ON p.rfd_id = r.id
                   GROUP BY r.id ORDER BY r.codigo, r.creado DESC"""
            ).fetchall()
        resultado = []
        for f in filas:
            calidad = json.loads(f["calidad_json"]) if f["calidad_json"] else None
            resultado.append({
                "id": f["id"], "codigo": f["codigo"], "cliente": f["cliente"], "titulo": f["titulo"], "version": f["version"],
                "padre_id": f["padre_id"], "creado": f["creado"], "origen": f["origen"], "proveedor": f["proveedor"],
                "modelo": f["modelo"], "calidad": calidad["puntaje"] if calidad else None,
                "preguntas": f["preguntas"] or 0, "abiertas": f["abiertas"] or 0, "respondidas": f["respondidas"] or 0,
                "mejorado": bool(f["hijos"]), "archivo": Path(f["ruta_docx"]).name if f["ruta_docx"] else None,
            })
        return resultado

    def obtener(self, rfd_id: int) -> dict[str, Any]:
        with self._conexion() as c:
            f = c.execute("SELECT * FROM rfds WHERE id = ?", (rfd_id,)).fetchone()
        if f is None:
            raise KeyError(f"No existe el RFD {rfd_id}.")
        return {
            "id": f["id"], "codigo": f["codigo"], "cliente": f["cliente"], "titulo": f["titulo"], "version": f["version"],
            "padre_id": f["padre_id"], "creado": f["creado"], "origen": f["origen"], "proveedor": f["proveedor"], "modelo": f["modelo"],
            "datos": json.loads(f["datos_json"]),
            "analisis": json.loads(f["analisis_json"]) if f["analisis_json"] else None,
            "calidad": json.loads(f["calidad_json"]) if f["calidad_json"] else None,
            "uso": json.loads(f["uso_json"]) if f["uso_json"] else None,
            "hallazgos": json.loads(f["hallazgos_json"] or "[]"),
            "ruta_docx": f["ruta_docx"], "ruta_pdf": f["ruta_pdf"], "ruta_cuestionario": f["ruta_cuestionario"],
        }

    def preguntas(self, rfd_id: int) -> list[dict[str, Any]]:
        with self._conexion() as c:
            filas = c.execute("SELECT * FROM preguntas WHERE rfd_id = ? ORDER BY pid", (rfd_id,)).fetchall()
        return [{"pid": f["pid"], "tema": f["tema"], "contexto": f["contexto"], "pregunta": f["pregunta"],
                 "relacion": json.loads(f["relacion_json"]), "respuesta": f["respuesta"], "estado": f["estado"],
                 "respondida_en": f["respondida_en"]} for f in filas]

    def respuestas(self, rfd_id: int) -> dict[str, str]:
        return {p["pid"]: p["respuesta"] for p in self.preguntas(rfd_id) if p["estado"] == "respondida"}

    # ------------------------------------------------------------------ reglas del equipo
    @staticmethod
    def _regla(f: sqlite3.Row) -> Regla:
        return Regla(id=f["id"], tipo=f["tipo"], texto=f["texto"], seccion=f["seccion"], patron=f["patron"],
                     cliente=f["cliente"], activa=bool(f["activa"]))

    def reglas(self) -> list[Regla]:
        with self._conexion() as c:
            return [self._regla(f) for f in c.execute("SELECT * FROM reglas ORDER BY activa DESC, cliente, id")]

    def reglas_para(self, cliente: str) -> list[Regla]:
        """Reglas activas globales y las del cliente indicado (sin distinguir mayúsculas)."""
        with self._conexion() as c:
            filas = c.execute("SELECT * FROM reglas WHERE activa = 1 AND (cliente = '' OR lower(cliente) = lower(?)) ORDER BY id",
                              (cliente.strip(),)).fetchall()
        return [self._regla(f) for f in filas]

    def guardar_regla(self, r: Regla) -> Regla:
        r = validar_regla(r)
        with self._conexion() as c:
            if r.id is None:
                cur = c.execute("INSERT INTO reglas (tipo, texto, seccion, patron, cliente, activa, creada, actualizada) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (r.tipo, r.texto, r.seccion, r.patron, r.cliente, int(r.activa), _ahora(), _ahora()))
                r.id = int(cur.lastrowid)
            else:
                cur = c.execute("UPDATE reglas SET tipo = ?, texto = ?, seccion = ?, patron = ?, cliente = ?, activa = ?, actualizada = ? "
                                "WHERE id = ?", (r.tipo, r.texto, r.seccion, r.patron, r.cliente, int(r.activa), _ahora(), r.id))
                if cur.rowcount == 0:
                    raise KeyError(f"No existe la regla R{r.id}.")
        return r

    def eliminar_regla(self, regla_id: int) -> None:
        with self._conexion() as c:
            c.execute("DELETE FROM reglas WHERE id = ?", (regla_id,))

    # ------------------------------------------------------------------ importación
    def importar_salidas(self, carpeta: Path) -> int:
        """Registra los RFD que ya existen en la carpeta de salidas (JSON junto a su .docx)."""
        with self._conexion() as c:
            conocidos = {r[0] for r in c.execute("SELECT ruta_docx FROM rfds WHERE ruta_docx IS NOT NULL")}
        n = 0
        for ruta in sorted(carpeta.glob("*.json"), key=lambda p: p.stat().st_mtime):
            if ruta.name.endswith((".analisis.json", ".respuestas.json")):
                continue
            docx = ruta.with_suffix(".docx")
            if not docx.is_file() or str(docx) in conocidos:
                continue
            try:
                datos = normalizar(json.loads(ruta.read_text(encoding="utf-8-sig")))
                validar_estructura(datos)
            except (ValueError, KeyError):
                continue
            ruta_a = ruta.with_name(ruta.stem + ".analisis.json")
            analisis = json.loads(ruta_a.read_text(encoding="utf-8")) if ruta_a.is_file() else None
            pdf = docx.with_suffix(".pdf")
            self.registrar(datos, origen="importado", ruta_docx=docx, analisis=analisis,
                           ruta_pdf=str(pdf) if pdf.is_file() else None)
            n += 1
        return n
