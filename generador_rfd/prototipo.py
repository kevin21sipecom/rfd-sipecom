"""Prototipo del cambio a partir del proyecto ORIGINAL: se levanta, se capturan sus pantallas y su diseño real, y la IA
construye el prototipo conversando. El prototipo conserva el diseño del proyecto; nunca se trata como una referencia de estilo.

Seguridad: levantar un proyecto ejecuta SU código en este equipo. Por eso la detección nunca ejecuta nada y el comando se
muestra y se confirma en la interfaz antes de iniciarlo; el proceso corre sin shell y con la carpeta del proyecto como cwd.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from .modelo import INTEGRIDAD, invocar
from .proyecto import DIRS_IGNORADOS

MAX_DISENO = 120_000
MAX_ARCHIVO_DISENO = 30_000
DIRS_DISENO_IGNORADOS = DIRS_IGNORADOS | {".venv", "venv", "build", ".next", ".nuxt", "coverage", "__pycache__", "out", "vendor"}
EXT_ESTILO = {".css", ".scss", ".sass", ".less"}
RE_TOKENS = re.compile(r"^(tailwind\.config\.\w+|theme\.\w+|tokens?\.\w+|variables?\.\w+|_variables\.\w+|design-tokens\.\w+)$", re.I)
RE_MAKE = re.compile(r"^(dev|start|run|serve)\s*:", re.M)
SCRIPTS = ("dev", "start", "serve")
PUERTOS_CONOCIDOS = (("vite", 5173), ("next", 3000), ("ng serve", 4200), ("react-scripts", 3000), ("nuxt", 3000), ("webpack", 8080))


def _ejecutable(nombre: str) -> str:
    """Ruta completa del ejecutable; en Windows resuelve shims como npm.cmd o bun.CMD."""
    return shutil.which(nombre) or nombre


def _puerto_libre(inicial: int = 8765) -> int:
    for puerto in range(inicial, inicial + 100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", puerto)) != 0:
                return puerto
    return inicial


def _gestor(carpeta: Path) -> str:
    if (carpeta / "bun.lock").is_file() or (carpeta / "bun.lockb").is_file():
        return "bun"
    if (carpeta / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (carpeta / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _url_de_script(texto: str) -> str | None:
    for marca, puerto in PUERTOS_CONOCIDOS:
        if marca in texto:
            return f"http://localhost:{puerto}"
    return None


def _comandos_de(carpeta: Path) -> list[dict[str, Any]]:
    """Comandos candidatos de una sola carpeta. Sólo lee archivos: no ejecuta nada."""
    encontrados: list[dict[str, Any]] = []
    cwd = str(carpeta)
    paquete = carpeta / "package.json"
    if paquete.is_file():
        try:
            scripts = json.loads(paquete.read_text(encoding="utf-8-sig")).get("scripts", {})
        except (OSError, ValueError):
            scripts = {}
        gestor = _gestor(carpeta)
        for nombre in SCRIPTS:
            if isinstance(scripts, dict) and isinstance(scripts.get(nombre), str):
                args = [nombre] if gestor == "yarn" else ["run", nombre]
                encontrados.append({"etiqueta": f"{gestor} {' '.join(args)}", "comando": [_ejecutable(gestor), *args],
                                    "cwd": cwd, "url_esperada": _url_de_script(scripts[nombre])})
    makefile = carpeta / "Makefile"
    if makefile.is_file():
        try:
            objetivos = RE_MAKE.findall(makefile.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            objetivos = []
        for objetivo in dict.fromkeys(objetivos):
            encontrados.append({"etiqueta": f"make {objetivo}", "comando": [_ejecutable("make"), objetivo], "cwd": cwd, "url_esperada": None})
    if (carpeta / "manage.py").is_file():
        encontrados.append({"etiqueta": "python manage.py runserver", "comando": [_ejecutable("python"), "manage.py", "runserver"],
                            "cwd": cwd, "url_esperada": "http://127.0.0.1:8000"})
    if (carpeta / "index.html").is_file():
        puerto = _puerto_libre()
        encontrados.append({"etiqueta": f"python -m http.server {puerto} (sitio estático)",
                            "comando": [sys.executable, "-m", "http.server", str(puerto), "--bind", "127.0.0.1"],
                            "cwd": cwd, "url_esperada": f"http://127.0.0.1:{puerto}"})
    return encontrados


def partir_comando(texto: str) -> list[str]:
    """Comando escrito por el usuario → lista de argumentos (el proceso se inicia siempre sin shell)."""
    try:
        partes = shlex.split(texto, posix=os.name != "nt")
    except ValueError as e:
        raise ValueError(f"El comando no es válido: {e}") from e
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in partes]


def validar_proyecto(ruta: str | Path) -> Path:
    carpeta = Path(str(ruta).strip().strip('"'))
    if not str(ruta).strip() or not carpeta.is_dir():
        raise ValueError("La ruta del proyecto debe ser una carpeta existente.")
    return carpeta.resolve()


def detectar_comandos(ruta: str | Path) -> list[dict[str, Any]]:
    """Comandos para levantar el proyecto: en la raíz y, si no hay, en sus subcarpetas directas (varios repositorios)."""
    raiz = validar_proyecto(ruta)
    encontrados = _comandos_de(raiz)
    if not encontrados:
        for hijo in sorted(p for p in raiz.iterdir() if p.is_dir() and p.name not in DIRS_DISENO_IGNORADOS and not p.name.startswith(".")):
            encontrados += _comandos_de(hijo)
    return encontrados


# ---------------------------------------------------------------- Diseño estático (cuando no se puede levantar)

def diseno_estatico(ruta: str | Path) -> str:
    """CSS, tokens y configuración de tema reales del proyecto (con tope), para reutilizar su diseño sin ejecutarlo."""
    try:
        raiz = validar_proyecto(ruta)
    except ValueError:
        return ""
    candidatos: list[tuple[int, int, Path]] = []
    for carpeta, subdirs, archivos in os.walk(raiz):
        subdirs[:] = [d for d in subdirs if d not in DIRS_DISENO_IGNORADOS]
        for nombre in archivos:
            p = Path(carpeta) / nombre
            if nombre.endswith((".min.css", ".min.js")):
                continue
            prioridad = 0 if RE_TOKENS.match(nombre) else 1 if p.suffix.lower() in EXT_ESTILO else None
            if prioridad is not None:
                candidatos.append((prioridad, len(p.relative_to(raiz).parts), p))
    partes: list[str] = []
    total = 0
    for _, _, p in sorted(candidatos):
        if total >= MAX_DISENO:
            break
        try:
            contenido = p.read_text(encoding="utf-8", errors="replace")[:min(MAX_ARCHIVO_DISENO, MAX_DISENO - total)]
        except OSError:
            continue
        partes.append(f"/* === {p.relative_to(raiz).as_posix()} === */\n{contenido}")
        total += len(contenido)
    return "\n\n".join(partes)


# ---------------------------------------------------------------- Proceso del proyecto original

WINDOWS = os.name == "nt"
MAX_LINEAS_LOG = 200
RE_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]):\d+", re.I)
RE_HOST_PUERTO = re.compile(r"https?://(\[[^\]]+\]|[^:/]+):(\d+)")
RE_ANSI =re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TIEMPO_PUERTO = 0.4


def _puerto_abierto(host: str, puerto: int) -> bool:
    with socket.socket() as s:
        s.settimeout(TIEMPO_PUERTO)
        return s.connect_ex((host, puerto)) == 0


def _normalizar_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not re.match(r"^https?://[^\s/]+", url, re.I):
        raise ValueError("La URL debe comenzar por http:// o https://.")
    return url


class ProcesoEnEjecucion(RuntimeError):
    """El prototipo ya tiene un proceso vivo: sólo se permite uno por prototipo."""


class _Proceso:
    def __init__(self, proc: Any, url_esperada: str | None) -> None:
        self.proc, self.url_esperada = proc, url_esperada
        self.url: str | None = None
        self.log: deque[str] = deque(maxlen=MAX_LINEAS_LOG)
        self.detenido = False
        self.lector_terminado = False

    @property
    def vivo(self) -> bool:
        return not self.detenido and self.proc.poll() is None


class Gestor:
    """Un proceso por prototipo: arranque sin shell, log acotado, URL detectada y cierre de todo el árbol de procesos."""

    def __init__(self) -> None:
        self._candado = threading.Lock()
        self._procesos: dict[str, _Proceso] = {}
        self._externos: dict[str, str] = {}

    def levantar(self, id_: str, comando: list[str], cwd: str | Path, url_esperada: str | None = None) -> dict[str, Any]:
        if not comando or not all(isinstance(c, str) and c.strip() for c in comando):
            raise ValueError("Indique el comando para levantar el proyecto.")
        with self._candado:
            previo = self._procesos.get(id_)
            if previo and previo.vivo:
                raise ProcesoEnEjecucion("Ya hay un proceso en ejecución para este prototipo. Deténgalo antes de iniciar otro.")
            self._externos.pop(id_, None)
            opciones: dict[str, Any] = {"cwd": str(cwd), "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                                        "text": True, "encoding": "utf-8", "errors": "replace",
                                        "env": {**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0", "NO_COLOR": "1", "BROWSER": "none"}}
            if WINDOWS:
                opciones["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                opciones["start_new_session"] = True
            try:
                proc = subprocess.Popen(comando, **opciones)  # sin shell=True: el comando es una lista de argumentos
            except (OSError, ValueError) as e:
                self._procesos.pop(id_, None)
                raise RuntimeError(f"No se pudo iniciar «{' '.join(comando)}»: {e}") from e
            p = _Proceso(proc, url_esperada)
            self._procesos[id_] = p
        threading.Thread(target=self._leer, args=(p,), daemon=True).start()
        return self.estado(id_)

    @staticmethod
    def _leer(p: _Proceso) -> None:
        try:
            for linea in p.proc.stdout or []:
                limpia = RE_ANSI.sub("", linea).rstrip()
                if limpia:
                    p.log.append(limpia)
                    if p.url is None and (m := RE_URL.search(limpia)):
                        p.url = m.group(0)
        except (OSError, ValueError):
            pass
        finally:
            p.lector_terminado = True

    def adoptar_url(self, id_: str, url: str) -> dict[str, Any]:
        """«Ya está corriendo»: el proyecto lo inició el usuario; sólo se recuerda su URL."""
        url = _normalizar_url(url)
        with self._candado:
            self._externos[id_] = url
        return self.estado(id_)

    def estado(self, id_: str) -> dict[str, Any]:
        with self._candado:
            p, externo = self._procesos.get(id_), self._externos.get(id_)
        if externo:
            return {"estado": "activo", "url": externo, "log": [], "codigo": None, "externo": True, "comando": None}
        if p is None:
            return {"estado": "detenido", "url": None, "log": [], "codigo": None, "externo": False}
        codigo = p.proc.poll()
        if p.detenido:
            estado = "detenido"
        elif codigo is not None:
            estado = "error" if codigo != 0 else "detenido"
        else:
            if p.url is None and p.url_esperada:
                m = RE_HOST_PUERTO.match(p.url_esperada)
                if m and _puerto_abierto(m.group(1).strip("[]"), int(m.group(2))):
                    p.url = p.url_esperada.rstrip("/")
            estado = "activo" if p.url else "iniciando"
        return {"estado": estado, "url": p.url if estado == "activo" else None, "log": list(p.log),
                "codigo": codigo if estado == "error" else None, "externo": False}

    def detener(self, id_: str) -> dict[str, Any]:
        with self._candado:
            p = self._procesos.get(id_)
            self._externos.pop(id_, None)
        if p and p.vivo:
            p.detenido = True
            _matar_arbol(p.proc)
        elif p:
            p.detenido = True
        return self.estado(id_)

    def detener_todos(self) -> None:
        with self._candado:
            ids = list(self._procesos) + list(self._externos)
        for id_ in ids:
            self.detener(id_)


def _matar_arbol(proc: Any) -> None:
    """Cierra el proceso y todos sus hijos (npm lanza node, que lanza vite…): taskkill /T en Windows, grupo de procesos en POSIX."""
    try:
        if WINDOWS:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False, timeout=15)
        else:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        proc.kill()


GESTOR = Gestor()


# ---------------------------------------------------------------- Captura de pantallas y diseño con Playwright (opcional)

MAX_HTML_PANTALLA = 200_000
MAX_CSS_CAPTURA = 400_000
MAX_RUTAS = 8
INSTALAR_PLAYWRIGHT = 'La captura necesita Playwright, que es opcional: instálelo con pip install -e ".[prototipo]". No descarga navegadores; usa Chrome o Edge.'
JS_DISENO = r"""() => {
  const css = [], variables = {};
  for (const hoja of document.styleSheets) {
    let reglas; try { reglas = hoja.cssRules; } catch (e) { continue; }
    for (const r of reglas) {
      css.push(r.cssText);
      if (r.selectorText && /(^|,)\s*(:root|html|body)\s*(,|$)/.test(r.selectorText))
        for (const p of r.style) if (p.startsWith('--')) variables[p] = r.style.getPropertyValue(p).trim();
    }
  }
  const estilo = (sel) => { const e = document.querySelector(sel); if (!e) return null; const s = getComputedStyle(e);
    return {color: s.color, fondo: s.backgroundColor, fuente: s.fontFamily, tamano: s.fontSize, peso: s.fontWeight, radio: s.borderRadius}; };
  const elementos = {};
  for (const [nombre, sel] of [['body', 'body'], ['titulo', 'h1, h2'], ['boton', "button, .btn, [class*='btn'], [class*='button']"],
      ['entrada', "input:not([type=hidden]), select, textarea"], ['enlace', 'a'], ['cabecera', 'header, nav']]) {
    const e = estilo(sel); if (e) elementos[nombre] = e;
  }
  const fuentes = [...new Set(Object.values(elementos).map((e) => e.fuente.split(',')[0].replace(/["']/g, '').trim()))];
  const b = elementos.boton, transparente = (c) => !c || c === 'rgba(0, 0, 0, 0)';
  const acento = b && !transparente(b.fondo) ? b.fondo : (elementos.enlace ? elementos.enlace.color : null);
  const s = elementos.body || {};
  return {html: document.documentElement.outerHTML, css: css.join('\n'),
    diseno: {fuentes, texto: s.color || null, fondo: s.fondo || null, acento, elementos, variables}};
}"""


def _sync_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(INSTALAR_PLAYWRIGHT) from e
    return sync_playwright


def _navegador(p: Any) -> Any:
    """Chrome o, si no está, Edge: los navegadores ya instalados (Playwright no descarga ninguno)."""
    fallos = []
    for canal in ("chrome", "msedge"):
        try:
            return p.chromium.launch(channel=canal)
        except Exception as e:  # noqa: BLE001 - el canal no está instalado: se prueba el siguiente
            fallos.append(f"{canal}: {e}")
    raise RuntimeError("No se encontró Chrome o Edge para abrir el proyecto (no se descarga ningún navegador). " + " | ".join(fallos)[:300])


# Muestra sólo la pantalla pedida (y las pantallas que la contienen); el resto queda oculto.
JS_MOSTRAR = r"""(indice) => {
  const todas = [...document.querySelectorAll('[data-pantalla]')];
  const objetivo = todas[indice];
  for (const e of todas) {
    e.style.removeProperty('display');
    if (e !== objetivo && !e.contains(objetivo)) e.style.setProperty('display', 'none', 'important');
  }
  // Una ventana emergente suele vivir dentro de un contenedor oculto sin marca: se muestra toda la cadena.
  for (let e = objetivo; e && e !== document.documentElement; e = e.parentElement) {
    const estilo = getComputedStyle(e);
    if (estilo.display === 'none') e.style.setProperty('display', 'block', 'important');
    if (estilo.visibility === 'hidden') e.style.setProperty('visibility', 'visible', 'important');
    if (estilo.opacity === '0') e.style.setProperty('opacity', '1', 'important');
    if (estilo.transform !== 'none') e.style.setProperty('transform', 'none', 'important');
  }
}"""


def capturar_pantallas_html(html: Path) -> list[tuple[str, bytes]]:
    """PNG de cada elemento data-pantalla del prototipo («RF-01 · principal»…), para insertarlo en el Word del RFD."""
    sync_playwright = _sync_playwright()
    capturas: list[tuple[str, bytes]] = []
    with sync_playwright() as p:
        navegador = _navegador(p)
        try:
            pagina = navegador.new_page(viewport={"width": 1366, "height": 850})
            pagina.set_content(html.read_text(encoding="utf-8"), wait_until="load")
            nombres = pagina.evaluate("() => [...document.querySelectorAll('[data-pantalla]')].map(e => e.dataset.pantalla.trim())")
            vistos: set[str] = set()
            for i, nombre in enumerate(nombres):
                if not nombre or nombre in vistos:
                    continue
                vistos.add(nombre)
                pagina.evaluate(JS_MOSTRAR, i)
                pagina.wait_for_timeout(150)
                try:
                    capturas.append((nombre, pagina.query_selector_all("[data-pantalla]")[i].screenshot(timeout=5_000)))
                except Exception:  # noqa: BLE001 - una pantalla que no se deja mostrar no impide capturar las demás
                    continue
        finally:
            navegador.close()
    return capturas


def capturar(url: str, rutas: list[str], destino: Path) -> list[dict[str, str]]:
    """Abre el proyecto en Chrome o Edge (sin descargar navegadores) y guarda por ruta: captura PNG, DOM, CSS y resumen del diseño."""
    base = _normalizar_url(url)
    limpias = list(dict.fromkeys("/" + r.strip().lstrip("/") for r in (rutas or ["/"]) if r.strip()))[:MAX_RUTAS] or ["/"]
    sync_playwright = _sync_playwright()
    destino.mkdir(parents=True, exist_ok=True)
    resultado: list[dict[str, str]] = []
    hojas: list[str] = []
    diseno: dict[str, Any] = {}
    with sync_playwright() as p:
        navegador = _navegador(p)
        try:
            pagina = navegador.new_page(viewport={"width": 1366, "height": 850})
            for i, ruta in enumerate(limpias, 1):
                destino_url = base + ruta
                try:
                    pagina.goto(destino_url, wait_until="load", timeout=30_000)
                    pagina.wait_for_timeout(800)
                    pagina.screenshot(path=str(destino / f"pantalla_{i}.png"), full_page=True)
                    datos = pagina.evaluate(JS_DISENO)
                except Exception as e:  # noqa: BLE001 - error de red o de página
                    raise RuntimeError(f"No se pudo capturar {destino_url}: {e}") from e
                (destino / f"pantalla_{i}.html").write_text(datos["html"][:MAX_HTML_PANTALLA], encoding="utf-8")
                if datos["css"] not in hojas:
                    hojas.append(datos["css"])
                diseno = diseno or datos["diseno"]
                resultado.append({"ruta": ruta, "imagen": f"pantalla_{i}.png", "html": f"pantalla_{i}.html"})
        finally:
            navegador.close()
    (destino / "estilos.css").write_text("\n\n".join(hojas)[:MAX_CSS_CAPTURA], encoding="utf-8")
    (destino / "diseno.json").write_text(json.dumps(diseno, ensure_ascii=False, indent=2), encoding="utf-8")
    (destino / "captura.json").write_text(json.dumps({"url": base, "pantallas": resultado}, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado


def pantallas_capturadas(destino: Path) -> list[dict[str, str]]:
    try:
        return json.loads((destino / "captura.json").read_text(encoding="utf-8"))["pantallas"]
    except (OSError, ValueError, KeyError):
        return []


def contexto_captura(destino: Path, max_css: int = 60_000, max_html: int = 30_000) -> str:
    """Diseño real capturado del proyecto en ejecución, listo para el prompt. Cadena vacía si no hay captura."""
    pantallas = pantallas_capturadas(destino)
    if not pantallas:
        return ""
    partes = []
    for nombre, titulo, tope in (("diseno.json", "Resumen del diseño (estilos calculados y variables CSS)", 20_000),
                                 ("estilos.css", "CSS completo del proyecto", max_css)):
        try:
            partes.append(f"## {titulo}\n{(destino / nombre).read_text(encoding='utf-8')[:tope]}")
        except OSError:
            pass
    for p in pantallas[:2]:
        try:
            partes.append(f"## DOM renderizado de la pantalla {p['ruta']}\n{(destino / p['html']).read_text(encoding='utf-8')[:max_html]}")
        except OSError:
            pass
    return "\n\n".join(partes)


# ---------------------------------------------------------------- Conversación: prototipo del cambio sobre el diseño original

MAX_HTML_PROTOTIPO = 1_500_000
MAX_HTML_ACTUAL = 150_000
RE_ID = re.compile(r"^[0-9a-f]{10}$")
RE_VERSION = re.compile(r"^v(\d+)\.html$")
ESQUEMA_PROTOTIPO: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["html", "resumen"],
    "properties": {"html": {"type": "string"}, "resumen": {"type": "string"}},
}

REGLAS_PROTOTIPO = """Eres un diseñador de producto que construye el prototipo de un CAMBIO sobre un sistema que ya existe.
El prototipo debe verse como el sistema original, porque es el mismo sistema con el cambio aplicado. Reglas:
- Entrega UN SOLO archivo HTML autocontenido (CSS en <style>, JavaScript mínimo en <script>) que muestre el CAMBIO descrito.
- REUTILIZA de forma literal las clases CSS, variables, tipografías, colores y la estructura de componentes del proyecto original que aparecen abajo. Copia sus reglas CSS en el <style>.
- No introduzcas un nuevo lenguaje de diseño, ni un framework, ni una librería, ni una fuente nueva. Trabaja sin CDN y sin peticiones externas: nada de <script src>, <link href> ni imágenes remotas.
- Marca lo que es nuevo o cambia con una insignia discreta «Nuevo» o «Modificado», sin alterar la apariencia original del resto.
- Simula la navegación entre pantallas con JavaScript mínimo en línea. No hagas llamadas reales a un servidor.
- Todo el texto va en español.
- Si falta información (datos, textos, pantallas), conserva marcadores de posición razonables y dilo en «resumen».
- «resumen»: 2 a 4 frases en español, dirigidas al usuario, con lo que cambió en esta versión y lo que quedó pendiente.
- Si ya existe un prototipo, modifícalo según el mensaje y conserva todo lo que el mensaje no pide cambiar."""


REGLAS_DOCUMENTO = """Eres un diseñador de producto que construye el prototipo navegable de las pantallas que describe un RFD, a partir de las maquetas de UI de ese documento.
Reglas:
- Entrega UN SOLO archivo HTML autocontenido (CSS en <style>, JavaScript mínimo en <script>), sin CDN y sin peticiones externas: nada de <script src>, <link href> ni imágenes remotas.
- Las imágenes adjuntas son las maquetas, en el orden de la lista «MAQUETAS DEL DOCUMENTO». Reprodúcelas con fidelidad: misma disposición (menú lateral, encabezado, migas de pan, título, tarjetas de indicadores, panel de filtros, matriz de resultados, paginación, ventanas emergentes), mismos colores, textos, columnas, botones e íconos aproximados con CSS o SVG en línea.
- Las pantallas del RFD que no tienen maqueta se diseñan con el mismo lenguaje visual de las maquetas (mismo menú, mismos componentes) y con las ventanas, secciones y campos del RFD.
- Usa datos de ejemplo verosímiles y coherentes con el RFD y con el formato de las maquetas (números de documento, fechas y montos).
- Simula la navegación con JavaScript mínimo en línea: el menú cambia de pantalla, «Detalle» abre su ventana emergente, los filtros se colapsan. No hagas llamadas reales a un servidor.
- Envuelve cada pantalla o ventana en un elemento con data-pantalla="<id del requerimiento> · <nombre de la ventana>" (p. ej. «RF-01 · principal», «RF-01 · Detalle») para poder capturarla por separado.
- Todo el texto va en español.
- «resumen»: 2 a 4 frases en español, dirigidas al usuario, con lo que se construyó o cambió y lo que quedó pendiente.
- Si ya existe un prototipo, modifícalo según el mensaje y conserva todo lo que el mensaje no pide cambiar."""


def _texto_rfd(datos: dict[str, Any], tope: int = 20_000) -> str:
    lineas = [f"Título: {datos.get('titulo', '')}", f"Objetivo: {datos.get('objetivo', '')}"]
    for r in datos.get("requerimientos", []):
        lineas.append(f"\n{r.get('id', '')} {r.get('nombre', '')}")
        lineas += [f"  {p}" for p in r.get("parrafos", [])[:3]]
        lineas += [f"  Elemento: {e.get('titulo', '')}: {e.get('detalle', '')}" for e in r.get("elementos", [])]
        for v in r.get("vistas", []):
            for ventana in v.get("ventanas", []):
                lineas.append(f"  Ventana {ventana.get('nombre', '')} ({v.get('portal', '')}): {ventana.get('descripcion', '')}")
                for s in ventana.get("secciones", []):
                    campos = ", ".join(f"{c.get('nombre', '')} [{c.get('tipo', '')}]" for c in s.get("campos", []))
                    lineas.append(f"    {s.get('nombre', '')}: {campos}")
        lineas += [f"  Paso {f.get('numero', '')}: {f.get('actor', '')} · {f.get('componente', '')} · {f.get('accion', '')}" for f in r.get("flujo", [])]
        lineas += [f"  Criterio: {c}" for c in r.get("criterios_aceptacion", [])]
    return "\n".join(lineas)[:tope]


def prompt_prototipo(*, mensaje: str, diseno: str, html_actual: str, rfd: dict[str, Any] | None, chat: list[dict[str, Any]],
                     maquetas: list[dict[str, Any]] | None = None, modo: str = "proyecto") -> str:
    partes = [REGLAS_DOCUMENTO if modo == "documento" else REGLAS_PROTOTIPO, INTEGRIDAD]
    if rfd:
        partes.append("# RFD que describe el cambio (requerimientos, ventanas, campos y flujos)\n" + _texto_rfd(rfd))
    if maquetas:
        partes.append("# MAQUETAS DEL DOCUMENTO (imágenes adjuntas, en este orden)\n" + "\n".join(
            f"{i}. {m['archivo']} — {m.get('titulo') or 'sin título'}" + (f": «{m['contexto']}»" if m.get("contexto") else "")
            for i, m in enumerate(maquetas, 1)))
    if modo != "documento":
        partes.append("# Diseño del proyecto ORIGINAL (úsalo tal cual)\n" + (diseno or "No hay diseño disponible: usa una apariencia neutra y dilo en «resumen»."))
    if html_actual:
        partes.append("# Prototipo actual (última versión)\n" + html_actual[:MAX_HTML_ACTUAL])
    if chat:
        partes.append("# Conversación previa\n" + "\n".join(
            f"{'Usuario' if m['rol'] == 'usuario' else 'Asistente'}: {m['texto']}" for m in chat[-8:]))
    partes.append("# Mensaje del usuario\n" + mensaje)
    return "\n\n".join(partes)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


MODOS = ("proyecto", "documento")
MAX_MAQUETAS = 12


def crear_prototipo(raiz: Path, ruta_proyecto: str | Path | None, rfd_id: int | None = None, modo: str = "proyecto") -> str:
    """«proyecto»: el cambio sobre el sistema original (se levanta y se captura). «documento»: sólo las maquetas del RFD."""
    if modo not in MODOS:
        raise ValueError("El modo del prototipo debe ser «proyecto» o «documento».")
    ruta = str(validar_proyecto(ruta_proyecto)) if modo == "proyecto" else ""
    id_ = uuid.uuid4().hex[:10]
    carpeta = raiz / id_
    carpeta.mkdir(parents=True)
    (carpeta / "meta.json").write_text(json.dumps(
        {"id": id_, "modo": modo, "ruta": ruta, "rfd_id": rfd_id, "creado": _ahora()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return id_


def agregar_imagenes(carpeta: Path, docx: Path) -> list[dict[str, Any]]:
    """Suma al prototipo las maquetas de un Word (sin repetir) y devuelve todas las disponibles."""
    from .imagenes import extraer_imagenes

    return extraer_imagenes(docx, carpeta / "imagenes")


def imagenes_de(carpeta: Path) -> list[dict[str, Any]]:
    from .imagenes import leer_indice

    return leer_indice(carpeta / "imagenes")


def _maquetas(carpeta: Path, elegidas: list[str] | None, modo: str) -> list[dict[str, Any]]:
    """Las maquetas elegidas, validadas contra el índice; sin elección, todas en el modo documento."""
    disponibles = {m["archivo"]: m for m in imagenes_de(carpeta)}
    if elegidas is None:
        return list(disponibles.values())[:MAX_MAQUETAS] if modo == "documento" else []
    for nombre in elegidas:
        if nombre not in disponibles:
            raise ValueError(f"La imagen «{nombre}» no existe en el prototipo.")
    if len(elegidas) > MAX_MAQUETAS:
        raise ValueError(f"Elija hasta {MAX_MAQUETAS} imágenes por mensaje.")
    return [disponibles[n] for n in dict.fromkeys(elegidas)]


def carpeta_de(raiz: Path, id_: str) -> Path:
    carpeta = raiz / id_
    if not RE_ID.match(id_) or not carpeta.is_dir():
        raise KeyError("Prototipo no encontrado.")
    return carpeta


def leer_meta(carpeta: Path) -> dict[str, Any]:
    return json.loads((carpeta / "meta.json").read_text(encoding="utf-8"))


def guardar_meta(carpeta: Path, **cambios: Any) -> dict[str, Any]:
    meta = {**leer_meta(carpeta), **cambios}
    (carpeta / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def leer_chat(carpeta: Path) -> list[dict[str, Any]]:
    try:
        return json.loads((carpeta / "chat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def versiones(carpeta: Path) -> list[int]:
    return sorted(int(m.group(1)) for p in carpeta.glob("v*.html") if (m := RE_VERSION.match(p.name)))


def recursos_externos(html: str) -> list[str]:
    """Servidores a los que el HTML pediría recursos (la vista previa los bloquea); los enlaces <a> no cuentan."""
    hosts: set[str] = set()
    for etiqueta in re.finditer(r"<(\w+)\b([^>]*)>", html):
        if etiqueta.group(1).lower() != "a":
            hosts.update(m.group(1) for m in re.finditer(r"""\b(?:src|href|srcset|poster)\s*=\s*["']?\s*(?:https?:)?//([^"'\s/>]+)""", etiqueta.group(2), re.I))
    hosts.update(m.group(1) for m in re.finditer(r"""url\(\s*["']?(?:https?:)?//([^"')\s/]+)""", html, re.I))
    hosts.update(m.group(1) for m in re.finditer(r"""@import\s+["']?(?:https?:)?//([^"';\s/]+)""", html, re.I))
    return sorted(hosts)


def turno(carpeta: Path, mensaje: str, *, proveedor: str, modelo: str, directorio: Path, rfd: dict[str, Any] | None = None,
          esfuerzo: str = "", uso: Any = None, progreso: Any = None, imagenes: list[str] | None = None) -> dict[str, Any]:
    """Un turno del chat: arma el prompt (RFD + diseño original o maquetas + versión actual + mensaje), pide el HTML y guarda la versión.

    `imagenes`: nombres de las maquetas elegidas (img_01.png…); el modelo las recibe como imágenes, no como texto.
    """
    mensaje = mensaje.strip()
    if not mensaje:
        raise ValueError("Escriba qué cambio quiere ver en el prototipo.")
    avisar = progreso or (lambda paso, detalle: None)
    meta = leer_meta(carpeta)
    modo = meta.get("modo", "proyecto")
    maquetas = _maquetas(carpeta, imagenes, modo)
    avisar("fuentes", "Reuniendo las maquetas del documento" if modo == "documento" else "Reuniendo el diseño del proyecto original")
    diseno = "" if modo == "documento" else contexto_captura(carpeta / "captura") or diseno_estatico(meta["ruta"])
    previas = versiones(carpeta)
    actual = (carpeta / f"v{previas[-1]}.html").read_text(encoding="utf-8") if previas else ""
    chat = leer_chat(carpeta)
    avisar("modelo", f"Construyendo el prototipo con {len(maquetas)} maqueta(s)" if maquetas else "Construyendo el prototipo sobre el diseño original")
    respuesta = invocar(
        proveedor=proveedor, modelo=modelo, esquema=ESQUEMA_PROTOTIPO, directorio=directorio, uso=uso, esfuerzo=esfuerzo,
        prompt=prompt_prototipo(mensaje=mensaje, diseno=diseno, html_actual=actual, rfd=rfd, chat=chat, maquetas=maquetas, modo=modo),
        **({"imagenes": [carpeta / "imagenes" / m["archivo"] for m in maquetas]} if maquetas else {}),
    )
    html = respuesta.get("html", "") if isinstance(respuesta, dict) else ""
    if not isinstance(html, str) or not re.search(r"<!doctype|<html", html, re.I):
        raise ValueError("La respuesta del modelo no contiene un documento HTML válido.")
    if len(html) > MAX_HTML_PROTOTIPO:
        raise ValueError("El HTML generado supera el tamaño permitido; pida un prototipo más acotado.")
    resumen = str(respuesta.get("resumen", "")).strip()
    if externos := recursos_externos(html):
        resumen += f" Aviso: el HTML pide recursos externos ({', '.join(externos)}) que la vista previa bloquea."
    version = (previas[-1] if previas else 0) + 1
    (carpeta / f"v{version}.html").write_text(html, encoding="utf-8")
    cuando = _ahora()
    chat += [{"rol": "usuario", "texto": mensaje, "cuando": cuando},
             {"rol": "ia", "texto": resumen, "cuando": cuando, "version": version}]
    (carpeta / "chat.json").write_text(json.dumps(chat, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"version": version, "resumen": resumen}
