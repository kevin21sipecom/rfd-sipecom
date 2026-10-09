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
from .pipeline import PLANTILLA, RAIZ, Opciones, OpcionesMejora, Resultado, generar as generar_rfd, mejorar, publicar
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


def _nombre_seguro(nombre: str) -> str:
    nombre = Path(nombre).name
    return re.sub(r"[^\w.\- ]+", "_", nombre).strip() or "archivo"


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
    if not transcripciones and not contextos:
        raise HTTPException(400, "Agregue al menos una transcripción o un documento de contexto.")
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
        cliente=cliente.strip(), codigo=codigo.strip(), tipo_proyecto=tipo_proyecto,
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
    return {
        **{k: r[k] for k in ("id", "codigo", "cliente", "titulo", "version", "padre_id", "creado", "origen", "proveedor", "modelo",
                             "calidad", "uso", "hallazgos")},
        "objetivo": d["objetivo"],
        "requerimientos": [{"id": x["id"], "nombre": x["nombre"]} for x in d["requerimientos"]],
        "definiciones": d["definiciones"],
        "cambios": d.get("cambios", []),
        "historial": d.get("historial", []),
        "preguntas": almacen().preguntas(rfd_id),
        "archivos": {t: bool(docx and docx.with_suffix(suf).is_file()) for t, suf in
                     [("docx", ".docx"), ("pdf", ".pdf"), ("cuestionario", ".cuestionario.docx"), ("revision", ".revision.md")]},
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
