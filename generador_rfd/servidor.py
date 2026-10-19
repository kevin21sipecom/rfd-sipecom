"""Servidor local (127.0.0.1) para la interfaz web en TypeScript."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .fuentes import EXTENSIONES
from .modelo import MODELO_CLAUDE_DEFECTO, MODELOS_CLAUDE, modelos_codex
from .almacen import Almacen
from .modelo import Uso, generar_preguntas
from .pipeline import (PLANTILLA, RAIZ, Opciones, OpcionesImportacion, OpcionesMejora, Resultado, continuar,
                       generar as generar_rfd, importar, leer_avance, mejorar, publicar)
from . import prototipo
from .proyecto import analizar_proyecto, herramientas
from .reglas import SECCIONES, Regla, bloque_prompt
from .revision import word_disponible

# En Windows el registro puede asociar .js a text/plain, y el navegador rechaza el módulo.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

PUERTO = 2122
ESTATICOS = Path(__file__).resolve().parent / "static"
SALIDAS = RAIZ / "salidas"
URL_PROVEEDOR = {"ollama": "http://127.0.0.1:11434/api/tags", "lmstudio": "http://127.0.0.1:1234/v1/models"}

app = FastAPI(title="Generador de RFD SIPECOM")
TIPOS_WEB = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


@app.middleware("http")
async def tipo_contenido(peticion, siguiente):  # type: ignore[no-untyped-def]
    respuesta = await siguiente(peticion)
    tipo = TIPOS_WEB.get(Path(peticion.url.path).suffix)
    if tipo:
        respuesta.headers["content-type"] = tipo
    return respuesta
_trabajos: dict[str, dict[str, Any]] = {}
_candado = threading.Lock()
_almacen: Almacen | None = None


def almacen() -> Almacen:
    """Historial SQLite (datos/rfd.db). Al abrirlo por primera vez registra los RFD ya presentes en salidas/."""
    global _almacen
    if _almacen is None:
        _almacen = Almacen(RAIZ / "datos" / "rfd.db")
        _almacen.importar_salidas(SALIDAS)
    return _almacen


def _registrar(r: Resultado, origen: str, proveedor: str, modelo: str, padre_id: int | None = None) -> int:
    ruta_a = r.salida.with_suffix(".analisis.json")
    analisis = json.loads(ruta_a.read_text(encoding="utf-8")) if ruta_a.is_file() else None
    return almacen().registrar(
        r.datos, origen=origen, ruta_docx=r.salida, padre_id=padre_id, proveedor=proveedor, modelo=modelo,
        analisis=analisis, calidad=r.calidad, uso=r.uso, hallazgos=[{"codigo": h.codigo, "mensaje": h.mensaje} for h in r.hallazgos],
        ruta_pdf=(r.revision_word or {}).get("pdf"),
    )


RESERVADOS_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _nombre_seguro(nombre: str) -> str:
    nombre = re.sub(r"[^\w.\- ]+", "_", Path(nombre).name).strip().rstrip(". ")
    if not nombre or nombre.split(".")[0].upper() in RESERVADOS_WINDOWS:
        return f"archivo_{nombre}" if nombre else "archivo"
    return nombre


def _resumen(r: Resultado) -> dict[str, Any]:
    datos, docx = r.datos, r.salida
    revision = docx.with_suffix(".revision.md")
    word = r.revision_word or {}
    return {
        "titulo": datos.get("titulo", ""),
        "cliente": datos.get("cliente", ""),
        "codigo": datos.get("codigo", ""),
        "objetivo": datos.get("objetivo", ""),
        "requerimientos": [
            {"id": x["id"], "nombre": x["nombre"], "evidencias": x.get("evidencias", [])}
            for x in datos.get("requerimientos", [])
        ] + ([{"id": datos["componentes"]["id"], "nombre": datos["componentes"]["titulo"] or "Adecuaciones de los componentes existentes",
               "evidencias": []}] if datos["componentes"]["items"] else []),
        "definiciones": datos.get("definiciones", []),
        "pendientes": datos.get("pendientes", []),
        "supuestos": datos.get("supuestos", []),
        "hallazgos": [{"codigo": h.codigo, "mensaje": h.mensaje} for h in r.hallazgos],
        "revision_md": revision.read_text(encoding="utf-8") if revision.is_file() else "",
        "carpeta": str(docx.parent),
        "archivo": docx.name,
        "paginas": word.get("paginas"),
        "pdf": bool(word.get("pdf")),
        "word": word.get("motivo") if word and not word.get("ok") else None,
        "calidad": r.calidad,
        "version": datos.get("version", "0.1"),
        "preguntas_cliente": datos.get("preguntas_cliente", []),
        "cambios": datos.get("cambios", []),
        "cuestionario": docx.with_suffix(".cuestionario.docx").is_file(),
    }


def _actualizar(id_: str, **cambios: Any) -> None:
    with _candado:
        _trabajos[id_].update(cambios)


def _trabajo(id_: str, o: Opciones) -> None:
    try:
        r = generar_rfd(o, lambda paso, detalle: _actualizar(id_, paso=paso, detalle=detalle))
        rfd_id = _registrar(r, "generado", o.proveedor, o.modelo)
        _actualizar(id_, estado="listo", paso="listo", fin=time.time(), uso=r.uso, resultado={**_resumen(r), "rfd_id": rfd_id},
                    fuentes=[{"id": f.id, "categoria": f.categoria, "nombre": f.nombre, "caracteres": len(f.contenido)} for f in r.fuentes])
    except Exception as e:  # noqa: BLE001 - el error se muestra en la interfaz
        _actualizar(id_, estado="error", error=str(e), fin=time.time())


@app.get("/api/entorno")
def entorno() -> dict[str, Any]:
    h = herramientas()
    return {
        "claude": shutil.which("claude"),
        "codex": shutil.which("codex"),
        "codegraph": h["codegraph"],
        "repomix": h["repomix"],
        "plantilla": PLANTILLA.is_file(),
        "word": word_disponible(),
        "salidas": str(SALIDAS),
        "extensiones": sorted(EXTENSIONES),
        "fecha": date.today().strftime("%d/%m/%Y"),
    }


_cache_codex: dict[str, Any] = {}


def _catalogo_codex() -> list[dict[str, Any]]:
    """`codex debug models` tarda unos segundos: se reutiliza durante 10 minutos."""
    if _cache_codex.get("hasta", 0) < time.time():
        _cache_codex.update(modelos=modelos_codex(), hasta=time.time() + 600)
    return _cache_codex["modelos"]


@app.get("/api/modelos")
def modelos(proveedor: str) -> dict[str, Any]:
    if proveedor == "claude":
        return {"disponible": bool(shutil.which("claude")), "defecto": MODELO_CLAUDE_DEFECTO, "modelos": MODELOS_CLAUDE}
    if proveedor == "codex":
        try:
            lista = _catalogo_codex()
        except RuntimeError as e:
            return {"disponible": False, "defecto": "", "modelos": [], "detalle": str(e)}
        return {"disponible": True, "defecto": lista[0]["id"] if lista else "", "modelos": lista}
    url = URL_PROVEEDOR.get(proveedor)
    if not url:
        raise HTTPException(400, "Proveedor no admitido.")
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            carga = json.load(r)
        nombres = [x.get("name", x.get("id", "")) for x in carga.get("models", carga.get("data", []))]
        return {
            "disponible": True, "defecto": nombres[0] if nombres else "",
            "modelos": [{"id": n, "nombre": n, "detalle": f"Modelo cargado en {proveedor}"} for n in nombres],
        }
    except (OSError, ValueError):
        return {"disponible": False, "defecto": "", "modelos": [], "detalle": f"Sin respuesta en {url}"}


@app.get("/api/elegir-carpeta")
def elegir_carpeta() -> dict[str, str]:
    """Abre el selector nativo de carpetas en este equipo (el servidor sólo escucha en 127.0.0.1)."""
    codigo = (
        "import tkinter as tk; from tkinter import filedialog; r = tk.Tk(); r.withdraw(); "
        "r.attributes('-topmost', True); print(filedialog.askdirectory(title='Carpeta del código del proyecto') or '')"
    )
    p = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, encoding="utf-8", check=False)
    return {"ruta": str(Path(p.stdout.strip())) if p.stdout.strip() else ""}


class PeticionContexto(BaseModel):
    proyecto: str
    enfoque: str


@app.post("/api/contexto-codigo")
def contexto_codigo(p: PeticionContexto) -> dict[str, Any]:
    try:
        f = analizar_proyecto(Path(p.proyecto), p.enfoque)
    except (OSError, ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e)) from e
    return {"nombre": f.nombre, "contenido": f.contenido, "caracteres": len(f.contenido)}


@app.post("/api/generar")
async def generar(
    transcripciones: list[UploadFile] = File(default=[]),
    contextos: list[UploadFile] = File(default=[]),
    estilos: list[UploadFile] = File(default=[]),
    avances: list[UploadFile] = File(default=[]),
    cliente: str = Form(...),
    codigo: str = Form(...),
    tipo_proyecto: str = Form("existente"),
    titulo: str = Form(""),
    fecha: str = Form(""),
    proveedor: str = Form("claude"),
    modelo: str = Form(""),
    esfuerzo: str = Form(""),
    proyecto: str = Form(""),
    enfoque: str = Form(""),
    publico: bool = Form(False),
    revisar_word: bool = Form(True),
) -> dict[str, str]:
    if not cliente.strip() or not codigo.strip():
        raise HTTPException(400, "Indique cliente y código del RFD.")
    if not transcripciones and not contextos and not avances:
        raise HTTPException(400, "Agregue al menos una transcripción, un documento de contexto o un RFD en avance.")
    id_ = uuid.uuid4().hex[:12]
    entradas = SALIDAS / "_entradas" / id_
    entradas.mkdir(parents=True, exist_ok=True)

    async def guardar(archivos: list[UploadFile]) -> list[Path]:
        rutas = []
        for a in archivos:
            destino = entradas / _nombre_seguro(a.filename or "archivo")
            destino.write_bytes(await a.read())
            rutas.append(destino)
        return rutas

    opciones = Opciones(
        transcripciones=await guardar(transcripciones), contextos=await guardar(contextos), estilos=await guardar(estilos),
        avances=await guardar(avances), cliente=cliente.strip(), codigo=codigo.strip(), tipo_proyecto=tipo_proyecto,
        titulo=titulo.strip() or None, fecha=fecha.strip() or date.today().strftime("%d/%m/%Y"),
        proveedor=proveedor, modelo=modelo.strip() or (MODELO_CLAUDE_DEFECTO if proveedor == "claude" else ""),
        esfuerzo=esfuerzo.strip() if proveedor == "codex" else "",
        proyecto=Path(proyecto.strip()) if proyecto.strip() else None, enfoque=enfoque.strip(),
        publico=publico, revisar_word=revisar_word, reglas=almacen().reglas_para(cliente),
        salida=SALIDAS / f"RFD_{_nombre_seguro(codigo.strip()).replace(' ', '_')}.docx",
    )
    with _candado:
        _trabajos[id_] = {"id": id_, "estado": "en_curso", "paso": "cola", "inicio": time.time(), "proveedor": proveedor, "detalle": "En cola",
                         "modelo": " · ".join(x for x in (opciones.modelo or "por defecto", opciones.esfuerzo) if x)}
    threading.Thread(target=_trabajo, args=(id_, opciones), daemon=True).start()
    return {"id": id_}


@app.post("/api/demo")
def demo() -> dict[str, str]:
    id_ = uuid.uuid4().hex[:12]
    salida = SALIDAS / "RFD_DEMO_SIPECOM.docx"
    inicio = time.time()
    try:
        datos = json.loads((RAIZ / "ejemplos" / "rfd_demo.json").read_text(encoding="utf-8-sig"))
        r = publicar(datos, salida, PLANTILLA, True)
    except (OSError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    with _candado:
        _trabajos[id_] = {
            "id": id_, "estado": "listo", "paso": "listo", "inicio": inicio, "fin": time.time(),
            "proveedor": "demo", "modelo": "", "resultado": _resumen(r),
        }
    return {"id": id_}


@app.get("/api/trabajos/{id_}")
def trabajo(id_: str) -> dict[str, Any]:
    with _candado:
        t = _trabajos.get(id_)
        if not t:
            raise HTTPException(404, "Trabajo no encontrado.")
        return dict(t)


def _ruta_resultado(id_: str, tipo: str) -> Path:
    t = trabajo(id_)
    if t.get("estado") != "listo":
        raise HTTPException(409, "El trabajo aún no termina.")
    docx = Path(t["resultado"]["carpeta"]) / t["resultado"]["archivo"]
    sufijos = {"docx": ".docx", "json": ".json", "revision": ".revision.md", "pdf": ".pdf", "analisis": ".analisis.json",
               "cuestionario": ".cuestionario.docx"}
    if tipo not in sufijos:
        raise HTTPException(400, "Tipo de archivo no válido.")
    return docx.with_suffix(sufijos[tipo])


@app.get("/api/trabajos/{id_}/archivo/{tipo}")
def descargar(id_: str, tipo: str) -> FileResponse:
    ruta = _ruta_resultado(id_, tipo)
    if not ruta.is_file():
        raise HTTPException(404, "El archivo no se generó.")
    return FileResponse(ruta, filename=ruta.name)


@app.post("/api/trabajos/{id_}/abrir")
def abrir(id_: str, tipo: str = "carpeta") -> dict[str, bool]:
    ruta = _ruta_resultado(id_, "pdf" if tipo == "pdf" else "docx")
    objetivo = ruta.parent if tipo == "carpeta" else ruta
    if hasattr(os, "startfile"):
        os.startfile(objetivo)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(objetivo)])
    return {"ok": True}


# ---------------------------------------------------------------- Historial (SQLite) y mejora con respuestas

@app.get("/api/rfds")
def rfds() -> list[dict[str, Any]]:
    return almacen().listar()


@app.get("/api/rfds/{rfd_id}")
def rfd(rfd_id: int) -> dict[str, Any]:
    try:
        r = almacen().obtener(rfd_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    d = r["datos"]
    docx = Path(r["ruta_docx"]) if r["ruta_docx"] else None
    html_prototipo = _prototipo_html_rfd(r)
    return {
        **{k: r[k] for k in ("id", "codigo", "cliente", "titulo", "version", "padre_id", "creado", "origen", "proveedor", "modelo",
                             "calidad", "uso", "hallazgos")},
        "objetivo": d["objetivo"],
        "requerimientos": [{"id": x["id"], "nombre": x["nombre"]} for x in d["requerimientos"]],
        "definiciones": d["definiciones"],
        "cambios": d.get("cambios", []),
        "historial": d.get("historial", []),
        "preguntas": almacen().preguntas(rfd_id),
        "archivos": {**{t: bool(docx and docx.with_suffix(suf).is_file()) for t, suf in
                        [("docx", ".docx"), ("pdf", ".pdf"), ("cuestionario", ".cuestionario.docx"), ("revision", ".revision.md")]},
                     "prototipo": bool(html_prototipo and html_prototipo.is_file())},
    }


class PeticionRespuesta(BaseModel):
    respuesta: str


@app.put("/api/rfds/{rfd_id}/preguntas/{pid}")
def responder(rfd_id: int, pid: str, p: PeticionRespuesta) -> dict[str, Any]:
    try:
        return almacen().responder(rfd_id, pid, p.respuesta)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/rfds/{rfd_id}/cuestionario")
async def cargar_cuestionario(rfd_id: int, archivo: UploadFile = File(...)) -> dict[str, Any]:
    from .cuestionario import leer_cuestionario

    destino = SALIDAS / "_entradas" / f"cuestionario-{rfd_id}-{uuid.uuid4().hex[:6]}.docx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(await archivo.read())
    try:
        respuestas = leer_cuestionario(destino)
    except Exception as e:  # noqa: BLE001 - archivo que no es un cuestionario válido
        raise HTTPException(400, f"No se pudo leer el cuestionario: {e}") from e
    n = almacen().responder_varias(rfd_id, respuestas)
    return {"leidas": len(respuestas), "guardadas": n, "preguntas": almacen().preguntas(rfd_id)}


@app.get("/api/rfds/{rfd_id}/archivo/{tipo}")
def archivo_rfd(rfd_id: int, tipo: str) -> FileResponse:
    sufijos = {"docx": ".docx", "pdf": ".pdf", "cuestionario": ".cuestionario.docx", "revision": ".revision.md", "json": ".json"}
    r = almacen().obtener(rfd_id)
    if tipo == "prototipo":
        html = _prototipo_html_rfd(r)
        if html is None or not html.is_file():
            raise HTTPException(404, "El RFD no tiene un prototipo adjunto.")
        return FileResponse(html, filename=html.name, media_type="text/html", headers={"Content-Security-Policy": CSP_PROTOTIPO})
    if tipo not in sufijos or not r["ruta_docx"]:
        raise HTTPException(404, "Archivo no disponible.")
    ruta = Path(r["ruta_docx"]).with_suffix(sufijos[tipo])
    if not ruta.is_file():
        raise HTTPException(404, "El archivo no existe en disco.")
    return FileResponse(ruta, filename=ruta.name)


@app.post("/api/rfds/{rfd_id}/abrir")
def abrir_rfd(rfd_id: int, tipo: str = "docx") -> dict[str, bool]:
    r = almacen().obtener(rfd_id)
    if not r["ruta_docx"]:
        raise HTTPException(404, "Archivo no disponible.")
    ruta = Path(r["ruta_docx"])
    objetivo = {"carpeta": ruta.parent, "pdf": ruta.with_suffix(".pdf"), "cuestionario": ruta.with_suffix(".cuestionario.docx")}.get(tipo, ruta)
    if hasattr(os, "startfile"):
        os.startfile(objetivo)  # type: ignore[attr-defined]
    return {"ok": True}


@app.delete("/api/rfds/{rfd_id}")
def eliminar_rfd(rfd_id: int) -> dict[str, bool]:
    almacen().eliminar(rfd_id)
    return {"ok": True}


def _nuevo_trabajo(proveedor: str, modelo: str, esfuerzo: str, tipo: str) -> str:
    id_ = uuid.uuid4().hex[:12]
    with _candado:
        _trabajos[id_] = {"id": id_, "tipo": tipo, "estado": "en_curso", "paso": "cola", "inicio": time.time(), "proveedor": proveedor,
                          "detalle": "En cola", "modelo": " · ".join(x for x in (modelo or "por defecto", esfuerzo) if x)}
    return id_


def _modelo_de(proveedor: str, modelo: str) -> str:
    return modelo.strip() or (MODELO_CLAUDE_DEFECTO if proveedor == "claude" else "")


@app.post("/api/rfds/{rfd_id}/mejorar")
async def mejorar_rfd(
    rfd_id: int,
    adjuntos: list[UploadFile] = File(default=[]),
    proveedor: str = Form("claude"),
    modelo: str = Form(""),
    esfuerzo: str = Form(""),
    revisar_word: bool = Form(True),
) -> dict[str, str]:
    try:
        base = almacen().obtener(rfd_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    respuestas = almacen().respuestas(rfd_id)
    id_ = _nuevo_trabajo(proveedor, modelo, esfuerzo, "mejora")
    entradas = SALIDAS / "_entradas" / id_
    entradas.mkdir(parents=True, exist_ok=True)
    rutas = []
    for a in adjuntos:
        destino = entradas / _nombre_seguro(a.filename or "adjunto")
        destino.write_bytes(await a.read())
        rutas.append(destino)
    if not respuestas and not rutas:
        with _candado:
            _trabajos.pop(id_, None)
        raise HTTPException(400, "Responda al menos una pregunta o adjunte un documento del cliente.")
    o = OpcionesMejora(
        base=Path(base["ruta_docx"] or SALIDAS / f"RFD_{_nombre_seguro(base['codigo'])}.docx"), salida_dir=SALIDAS,
        respuestas=respuestas, adjuntos=rutas, proveedor=proveedor, modelo=_modelo_de(proveedor, modelo),
        esfuerzo=esfuerzo.strip() if proveedor == "codex" else "", revisar_word=revisar_word,
        datos_base=base["datos"], analisis_base=base["analisis"], reglas=almacen().reglas_para(base["cliente"]),
    )

    def trabajo() -> None:
        try:
            r = mejorar(o, lambda paso, detalle: _actualizar(id_, paso=paso, detalle=detalle))
            nuevo_id = _registrar(r, "mejorado", o.proveedor, o.modelo, padre_id=rfd_id)
            _actualizar(id_, estado="listo", paso="listo", fin=time.time(), uso=r.uso,
                        resultado={**_resumen(r), "rfd_id": nuevo_id})
        except Exception as e:  # noqa: BLE001
            _actualizar(id_, estado="error", error=str(e), fin=time.time())

    threading.Thread(target=trabajo, daemon=True).start()
    return {"id": id_}


@app.post("/api/rfds/importar")
async def importar_rfd(
    archivo: UploadFile = File(...),
    cliente: str = Form(...),
    codigo: str = Form(...),
    titulo: str = Form(""),
    tipo_proyecto: str = Form("existente"),
    proveedor: str = Form("claude"),
    modelo: str = Form(""),
    esfuerzo: str = Form(""),
) -> dict[str, str]:
    """Registra en el historial un RFD a medio redactar (.docx) para continuarlo después."""
    if not cliente.strip() or not codigo.strip():
        raise HTTPException(400, "Indique cliente y código del RFD.")
    id_ = _nuevo_trabajo(proveedor, modelo, esfuerzo, "importacion")
    entradas = SALIDAS / "_entradas" / id_
    entradas.mkdir(parents=True, exist_ok=True)
    destino = entradas / _nombre_seguro(archivo.filename or "avance.docx")
    try:
        destino.write_bytes(await archivo.read())
        leer_avance(destino)
    except Exception as e:  # noqa: BLE001 - cualquier fallo de lectura debe liberar el trabajo, no dejarlo «en curso»
        with _candado:
            _trabajos.pop(id_, None)
        raise HTTPException(400, str(e) if isinstance(e, ValueError) else "No se pudo leer el archivo cargado.") from e
    o = OpcionesImportacion(
        archivo=destino, salida_dir=SALIDAS, cliente=cliente.strip(), codigo=codigo.strip(), titulo=titulo.strip() or None,
        tipo_proyecto=tipo_proyecto, proveedor=proveedor, modelo=_modelo_de(proveedor, modelo),
        esfuerzo=esfuerzo.strip() if proveedor == "codex" else "", reglas=almacen().reglas_para(cliente),
    )

    def trabajo() -> None:
        try:
            r = importar(o, lambda paso, detalle: _actualizar(id_, paso=paso, detalle=detalle))
            rfd_id = _registrar(r, "en_avance", o.proveedor, o.modelo)
            _actualizar(id_, estado="listo", paso="listo", fin=time.time(), uso=r.uso, resultado={**_resumen(r), "rfd_id": rfd_id})
        except Exception as e:  # noqa: BLE001
            _actualizar(id_, estado="error", error=str(e), fin=time.time())

    threading.Thread(target=trabajo, daemon=True).start()
    return {"id": id_}


@app.post("/api/rfds/{rfd_id}/continuar")
async def continuar_rfd(
    rfd_id: int,
    adjuntos: list[UploadFile] = File(default=[]),
    instruccion: str = Form(""),
    proveedor: str = Form("claude"),
    modelo: str = Form(""),
    esfuerzo: str = Form(""),
    revisar_word: bool = Form(True),
) -> dict[str, str]:
    """Nueva versión que conserva lo escrito y completa lo que falta; no necesita respuestas del cliente."""
    try:
        base = almacen().obtener(rfd_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    id_ = _nuevo_trabajo(proveedor, modelo, esfuerzo, "continuacion")
    entradas = SALIDAS / "_entradas" / id_
    entradas.mkdir(parents=True, exist_ok=True)
    rutas = []
    for a in adjuntos:
        destino = entradas / _nombre_seguro(a.filename or "contexto")
        destino.write_bytes(await a.read())
        rutas.append(destino)
    o = OpcionesMejora(
        base=Path(base["ruta_docx"] or SALIDAS / f"RFD_{_nombre_seguro(base['codigo'])}.docx"), salida_dir=SALIDAS,
        adjuntos=rutas, instruccion=instruccion.strip(), proveedor=proveedor, modelo=_modelo_de(proveedor, modelo),
        esfuerzo=esfuerzo.strip() if proveedor == "codex" else "", revisar_word=revisar_word,
        datos_base=base["datos"], analisis_base=base["analisis"], reglas=almacen().reglas_para(base["cliente"]),
    )

    def trabajo() -> None:
        try:
            r = continuar(o, lambda paso, detalle: _actualizar(id_, paso=paso, detalle=detalle))
            nuevo_id = _registrar(r, "continuado", o.proveedor, o.modelo, padre_id=rfd_id)
            _actualizar(id_, estado="listo", paso="listo", fin=time.time(), uso=r.uso, resultado={**_resumen(r), "rfd_id": nuevo_id})
        except Exception as e:  # noqa: BLE001
            _actualizar(id_, estado="error", error=str(e), fin=time.time())

    threading.Thread(target=trabajo, daemon=True).start()
    return {"id": id_}


@app.post("/api/rfds/{rfd_id}/preguntas")
def crear_preguntas(rfd_id: int, proveedor: str = Form("claude"), modelo: str = Form(""), esfuerzo: str = Form("")) -> dict[str, str]:
    """Para RFD anteriores a la sección de preguntas: las redacta sin modificar el documento."""
    base = almacen().obtener(rfd_id)
    id_ = _nuevo_trabajo(proveedor, modelo, esfuerzo, "preguntas")

    def trabajo() -> None:
        try:
            _actualizar(id_, paso="modelo", detalle="Redactando las preguntas para el cliente")
            uso = Uso()
            preguntas = generar_preguntas(datos=base["datos"], analisis=base["analisis"], proveedor=proveedor,
                                          modelo=_modelo_de(proveedor, modelo), directorio_salida=SALIDAS, uso=uso,
                                          esfuerzo=esfuerzo if proveedor == "codex" else "",
                                          reglas=bloque_prompt(almacen().reglas_para(base["cliente"])))
            datos = {**base["datos"], "preguntas_cliente": preguntas}
            docx = Path(base["ruta_docx"])
            _actualizar(id_, paso="word", detalle="Actualizando el Word y el cuestionario")
            r = publicar(datos, docx, revisar_word=word_disponible(), uso=uso.como_dict(), calidad=base["calidad"])
            nuevo_id = _registrar(r, base["origen"], base["proveedor"] or proveedor, base["modelo"] or modelo, padre_id=base["padre_id"])
            _actualizar(id_, estado="listo", paso="listo", fin=time.time(), uso=r.uso, resultado={**_resumen(r), "rfd_id": nuevo_id})
        except Exception as e:  # noqa: BLE001
            _actualizar(id_, estado="error", error=str(e), fin=time.time())

    threading.Thread(target=trabajo, daemon=True).start()
    return {"id": id_}


# ---------------------------------------------------------------- Reglas del equipo

class PeticionRegla(BaseModel):
    texto: str
    tipo: str = "evitar"
    seccion: str = "todo"
    patron: str = ""
    cliente: str = ""
    activa: bool = True


@app.get("/api/reglas")
def reglas(cliente: str = "") -> dict[str, Any]:
    todas = almacen().reglas()
    return {"reglas": [r.como_dict() for r in todas], "secciones": SECCIONES,
            "aplicables": [r.id for r in almacen().reglas_para(cliente)]}


@app.post("/api/reglas")
def crear_regla(p: PeticionRegla) -> dict[str, Any]:
    try:
        return almacen().guardar_regla(Regla(**p.model_dump())).como_dict()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/reglas/{regla_id}")
def editar_regla(regla_id: int, p: PeticionRegla) -> dict[str, Any]:
    try:
        return almacen().guardar_regla(Regla(id=regla_id, **p.model_dump())).como_dict()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@app.delete("/api/reglas/{regla_id}")
def eliminar_regla(regla_id: int) -> dict[str, bool]:
    almacen().eliminar_regla(regla_id)
    return {"ok": True}


# ---------------------------------------------------------------- Prototipos: el cambio sobre el diseño del sistema original

# Un turno de chat a la vez por prototipo: dos versiones simultáneas partirían de la misma «actual».
_proto_ocupados: set[str] = set()
RE_ARCHIVO_CAPTURA = re.compile(r"^(pantalla_\d{1,2}\.(?:png|html)|captura\.json|diseno\.json|estilos\.css)$")
TIPOS_CAPTURA = {".png": "image/png", ".html": "text/plain; charset=utf-8", ".json": "application/json", ".css": "text/plain; charset=utf-8"}
# La vista previa no puede pedir nada afuera ni acceder al origen de la aplicación.
CSP_PROTOTIPO = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                 "img-src data: blob:; font-src data:")


@app.on_event("shutdown")
def _detener_prototipos() -> None:
    prototipo.GESTOR.detener_todos()


def _raiz_prototipos() -> Path:
    return SALIDAS / "_prototipos"


def _carpeta_proto(id_: str) -> Path:
    try:
        return prototipo.carpeta_de(_raiz_prototipos(), id_)
    except KeyError as e:
        raise HTTPException(404, "Prototipo no encontrado.") from e


def _rfd_vinculado(rfd_id: int | None) -> dict[str, Any] | None:
    if rfd_id is None:
        return None
    try:
        r = almacen().obtener(rfd_id)
    except KeyError:
        return None
    return {"id": r["id"], "codigo": r["codigo"], "titulo": r["titulo"], "version": r["version"]}


def _prototipo_html_rfd(r: dict[str, Any]) -> Path | None:
    if not r["ruta_docx"]:
        return None
    return Path(r["ruta_docx"]).parent / f"RFD_{_nombre_seguro(r['codigo']).replace(' ', '_')}_prototipo.html"


@app.get("/api/prototipos/detectar")
def detectar_prototipo(ruta: str) -> dict[str, Any]:
    try:
        return {"comandos": prototipo.detectar_comandos(ruta)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class PeticionPrototipo(BaseModel):
    ruta: str
    rfd_id: int | None = None


@app.post("/api/prototipos")
def crear_prototipo(p: PeticionPrototipo) -> dict[str, str]:
    if p.rfd_id is not None:
        try:
            almacen().obtener(p.rfd_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
    try:
        return {"id": prototipo.crear_prototipo(_raiz_prototipos(), p.ruta, p.rfd_id)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/prototipos")
def prototipos() -> list[dict[str, Any]]:
    filas = []
    raiz = _raiz_prototipos()
    for carpeta in sorted(raiz.iterdir(), key=lambda c: c.stat().st_mtime, reverse=True) if raiz.is_dir() else []:
        if not (carpeta / "meta.json").is_file():
            continue
        meta = prototipo.leer_meta(carpeta)
        filas.append({"id": meta["id"], "ruta": meta["ruta"], "creado": meta.get("creado"), "versiones": len(prototipo.versiones(carpeta)),
                      "rfd": _rfd_vinculado(meta.get("rfd_id"))})
    return filas


@app.get("/api/prototipos/{id_}")
def detalle_prototipo(id_: str) -> dict[str, Any]:
    carpeta = _carpeta_proto(id_)
    meta = prototipo.leer_meta(carpeta)
    return {"id": meta["id"], "ruta": meta["ruta"], "creado": meta.get("creado"), "rfd": _rfd_vinculado(meta.get("rfd_id")),
            "chat": prototipo.leer_chat(carpeta), "versiones": prototipo.versiones(carpeta),
            "proceso": prototipo.GESTOR.estado(id_), "captura": {"pantallas": prototipo.pantallas_capturadas(carpeta / "captura")}}


class PeticionLevantar(BaseModel):
    comando: list[str] | str | None = None
    cwd: str | None = None
    url_esperada: str | None = None
    url: str | None = None


@app.post("/api/prototipos/{id_}/levantar")
def levantar_prototipo(id_: str, p: PeticionLevantar) -> dict[str, Any]:
    meta = prototipo.leer_meta(_carpeta_proto(id_))
    try:
        if p.url:
            return prototipo.GESTOR.adoptar_url(id_, p.url)
        proyecto = Path(meta["ruta"]).resolve()
        cwd = Path(p.cwd).resolve() if p.cwd else proyecto
        if cwd != proyecto and proyecto not in cwd.parents:
            raise ValueError("La carpeta de ejecución debe estar dentro del proyecto.")
        comando = prototipo.partir_comando(p.comando) if isinstance(p.comando, str) else (p.comando or [])
        return prototipo.GESTOR.levantar(id_, comando, cwd, p.url_esperada)
    except prototipo.ProcesoEnEjecucion as e:
        raise HTTPException(409, str(e)) from e
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/prototipos/{id_}/detener")
def detener_prototipo(id_: str) -> dict[str, Any]:
    _carpeta_proto(id_)
    return prototipo.GESTOR.detener(id_)


class PeticionCaptura(BaseModel):
    rutas: list[str] = ["/"]


@app.post("/api/prototipos/{id_}/capturar")
def capturar_prototipo(id_: str, p: PeticionCaptura) -> dict[str, str]:
    carpeta = _carpeta_proto(id_)
    estado = prototipo.GESTOR.estado(id_)
    if estado["estado"] != "activo" or not estado["url"]:
        raise HTTPException(409, "Levante el proyecto o indique la URL donde ya está corriendo antes de capturarlo.")
    trabajo_id = _nuevo_trabajo("", "", "", "captura")

    def trabajo() -> None:
        try:
            _actualizar(trabajo_id, paso="captura", detalle=f"Capturando {len(p.rutas)} pantalla(s) de {estado['url']}")
            pantallas = prototipo.capturar(estado["url"], p.rutas, carpeta / "captura")
            _actualizar(trabajo_id, estado="listo", paso="listo", fin=time.time(), resultado={"pantallas": pantallas})
        except Exception as e:  # noqa: BLE001 - el error se muestra en la interfaz
            _actualizar(trabajo_id, estado="error", error=str(e), fin=time.time())

    threading.Thread(target=trabajo, daemon=True).start()
    return {"id": trabajo_id}


@app.get("/api/prototipos/{id_}/captura/{nombre}")
def archivo_captura(id_: str, nombre: str) -> FileResponse:
    ruta = _carpeta_proto(id_) / "captura" / nombre
    if not RE_ARCHIVO_CAPTURA.match(nombre) or not ruta.is_file():
        raise HTTPException(404, "Archivo de captura no encontrado.")
    return FileResponse(ruta, media_type=TIPOS_CAPTURA[ruta.suffix])


@app.post("/api/prototipos/{id_}/mensaje")
def mensaje_prototipo(id_: str, texto: str = Form(""), proveedor: str = Form("claude"), modelo: str = Form(""),
                      esfuerzo: str = Form("")) -> dict[str, str]:
    carpeta = _carpeta_proto(id_)
    if not texto.strip():
        raise HTTPException(400, "Escriba qué cambio quiere ver en el prototipo.")
    with _candado:
        if id_ in _proto_ocupados:
            raise HTTPException(409, "El prototipo ya está generando una versión; espere a que termine.")
        _proto_ocupados.add(id_)
    trabajo_id = _nuevo_trabajo(proveedor, modelo, esfuerzo, "prototipo")
    rfd_id = prototipo.leer_meta(carpeta).get("rfd_id")

    def trabajo() -> None:
        try:
            uso = Uso()
            datos = almacen().obtener(rfd_id)["datos"] if rfd_id is not None else None
            r = prototipo.turno(carpeta, texto, proveedor=proveedor, modelo=_modelo_de(proveedor, modelo), directorio=carpeta, rfd=datos,
                                esfuerzo=esfuerzo if proveedor == "codex" else "", uso=uso,
                                progreso=lambda paso, detalle: _actualizar(trabajo_id, paso=paso, detalle=detalle))
            _actualizar(trabajo_id, estado="listo", paso="listo", fin=time.time(), uso=uso.como_dict(), resultado=r)
        except Exception as e:  # noqa: BLE001
            _actualizar(trabajo_id, estado="error", error=str(e), fin=time.time())
        finally:
            with _candado:
                _proto_ocupados.discard(id_)

    threading.Thread(target=trabajo, daemon=True).start()
    return {"id": trabajo_id}


@app.get("/api/prototipos/{id_}/v/{version}")
def version_prototipo(id_: str, version: int) -> HTMLResponse:
    ruta = _carpeta_proto(id_) / f"v{version}.html"
    if not ruta.is_file():
        raise HTTPException(404, "Versión no encontrada.")
    return HTMLResponse(ruta.read_text(encoding="utf-8"), headers={"Content-Security-Policy": CSP_PROTOTIPO})


class PeticionAdjuntar(BaseModel):
    version: int | None = None


@app.post("/api/prototipos/{id_}/adjuntar-rfd")
def adjuntar_prototipo(id_: str, p: PeticionAdjuntar) -> dict[str, Any]:
    carpeta = _carpeta_proto(id_)
    rfd_id = prototipo.leer_meta(carpeta).get("rfd_id")
    if rfd_id is None:
        raise HTTPException(400, "El prototipo no está vinculado a un RFD.")
    disponibles = prototipo.versiones(carpeta)
    if not disponibles:
        raise HTTPException(409, "El prototipo aún no tiene versiones.")
    version = p.version if p.version is not None else disponibles[-1]
    if version not in disponibles:
        raise HTTPException(404, "Versión no encontrada.")
    destino = _prototipo_html_rfd(almacen().obtener(rfd_id))
    if destino is None:
        raise HTTPException(409, "El RFD no tiene un Word en disco junto al cual guardar el prototipo.")
    shutil.copyfile(carpeta / f"v{version}.html", destino)
    return {"ok": True, "version": version, "archivo": destino.name}


if ESTATICOS.is_dir():
    app.mount("/", StaticFiles(directory=ESTATICOS, html=True), name="web")
else:
    @app.get("/", response_class=HTMLResponse)
    def sin_compilar() -> str:
        return "<p>La interfaz no está compilada. Ejecute <code>bun install</code> y <code>bun run build</code> en <code>web/</code>.</p>"


def iniciar(puerto: int = PUERTO, abrir_navegador: bool = True) -> None:
    import uvicorn

    url = f"http://127.0.0.1:{puerto}"
    print(f"Generador de RFD en {url}  (Ctrl+C para detener)")
    if abrir_navegador:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")
