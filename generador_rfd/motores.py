"""CLIs de IA admitidas: Claude Code, Codex, Antigravity (agy), Grok y OpenCode.

Siguiendo el contrato de `@sipecom/common-utils` (agent-cli.ts), cada CLI tiene su propia forma de recibir
el prompt, su catálogo de modelos y sus reglas: archivos de instrucciones globales (CLAUDE.md, AGENTS.md,
~/.grok/rules…), herramientas y permisos que, en una generación de RFD, deben quedar fuera. Este módulo
concentra esas diferencias; `modelo.invocar` sólo elige el adaptador.

| CLI       | Prompt                         | Salida estructurada            | Aislamiento                                        |
| --------- | ------------------------------ | ------------------------------ | -------------------------------------------------- |
| claude    | stdin                          | --json-schema (nativo)         | sin herramientas, MCP ni settings; system prompt    |
| codex     | stdin                          | --output-schema (nativo)       | read-only, efímero, --ignore-user-config/-rules     |
| agy       | stdin en NDJSON (stream-json)  | --json-schema (nativo)         | sandbox, sin slash commands, carpeta vacía          |
| grok      | --prompt-file                  | --json-schema (nativo)         | system prompt propio, sin subagentes ni web         |
| opencode  | stdin                          | esquema en el prompt + parseo  | --pure y OPENCODE_DISABLE_* (CLAUDE.md, proyecto)   |
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

NIVELES_CLASICOS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Cli:
    id: str
    nombre: str
    ejecutable: str
    proveedor: str              # empresa o servicio detrás de la CLI
    reglas: str                 # cómo se aísla de sus reglas e instrucciones propias
    costo: bool = False         # informa costo en USD


CLIS: dict[str, Cli] = {
    "claude": Cli("claude", "Claude Code", "claude", "Anthropic",
                  "Sin herramientas, MCP, plugins ni settings del usuario (CLAUDE.md fuera); sesión efímera.", costo=True),
    "codex": Cli("codex", "Codex", "codex", "OpenAI",
                 "Sólo lectura, efímero, sin config.toml ni reglas (AGENTS.md) del usuario."),
    "agy": Cli("agy", "Antigravity", "agy", "Google",
               "Sandbox, sin slash commands ni skills, en una carpeta vacía; prompt por stream-json."),
    "grok": Cli("grok", "Grok", "grok", "xAI",
                "System prompt propio que reemplaza al del agente, sin subagentes, plan ni búsqueda web.", costo=True),
    "opencode": Cli("opencode", "OpenCode", "opencode", "OpenCode",
                    "Modo --pure, sin CLAUDE.md, skills externas ni configuración de proyecto."),
}
PROVEEDORES = tuple(CLIS)


def ejecutable(cli: str) -> str | None:
    return shutil.which(CLIS[cli].ejecutable)


def _correr(comando: list[str], *, entrada: str | None = None, tiempo: int, cwd: Path | None = None,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(comando, input=entrada, text=True, encoding="utf-8", errors="replace", capture_output=True,
                              timeout=tiempo, check=False, cwd=cwd, env={**os.environ, **(env or {})},
                              stdin=None if entrada is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{Path(comando[0]).stem} superó el límite de {tiempo} segundos.") from e


def extraer_json(texto: str) -> Any:
    """Primer objeto JSON balanceado del texto (tolera bloques ```json y texto alrededor)."""
    texto = texto.strip()
    try:
        return json.loads(texto)
    except ValueError:
        pass
    decodificador = json.JSONDecoder()
    for m in re.finditer(r"\{", texto):
        try:
            obj, _ = decodificador.raw_decode(texto, m.start())
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    raise RuntimeError("La respuesta no contiene un objeto JSON.")


def instruccion_esquema(esquema: dict[str, Any]) -> str:
    return ("\n\nFORMATO DE RESPUESTA\nResponde ÚNICAMENTE con un objeto JSON válido que cumpla este JSON Schema, "
            "sin texto adicional ni bloques de código:\n" + json.dumps(esquema, ensure_ascii=False))


# ---------------------------------------------------------------- catálogos de modelos

def catalogo_agy(tiempo: int = 60) -> list[dict[str, Any]]:
    p = _correr([ejecutable("agy") or "agy", "models"], tiempo=tiempo)
    modelos = []
    for linea in (p.stdout or "").splitlines():
        partes = linea.strip().split("\t")
        if len(partes) == 2 and re.fullmatch(r"[\w.\-]+", partes[0]):
            modelos.append({"id": partes[0], "nombre": partes[1], "detalle": "", "niveles": list(NIVELES_CLASICOS), "nivel_defecto": ""})
    if not modelos:
        raise RuntimeError((p.stderr or p.stdout or "agy no devolvió modelos.").strip()[-300:])
    return modelos


def catalogo_grok(tiempo: int = 45) -> list[dict[str, Any]]:
    p = _correr([ejecutable("grok") or "grok", "models"], tiempo=tiempo)
    salida = (p.stdout or "") + (p.stderr or "")
    modelos = []
    for m in re.finditer(r"^\s*[*\-•]\s+([\w.\-]+)(\s+\(default\))?", salida, re.M):
        modelos.append({"id": m.group(1), "nombre": m.group(1), "detalle": "Modelo por defecto de Grok" if m.group(2) else "",
                        "niveles": ["low", "medium", "high"], "nivel_defecto": "", **({"etiqueta": "Por defecto"} if m.group(2) else {})})
    if "not authenticated" in salida.lower():
        raise RuntimeError("Grok no tiene sesión iniciada: ejecute «grok login» en una terminal.")
    if not modelos:
        raise RuntimeError(salida.strip()[-300:] or "grok no devolvió modelos.")
    return modelos


def catalogo_opencode(tiempo: int = 90) -> list[dict[str, Any]]:
    p = _correr([ejecutable("opencode") or "opencode", "models", "--verbose"], tiempo=tiempo, env=ENTORNO_OPENCODE)
    texto, decodificador, i, modelos = p.stdout or "", json.JSONDecoder(), 0, []
    patron = re.compile(r"^([\w.\-]+/[\w.\-:/]+)\s*$", re.M)
    while (m := patron.search(texto, i)) is not None:
        inicio = texto.find("{", m.end())
        datos: dict[str, Any] = {}
        i = m.end()
        siguiente = patron.search(texto, m.end())
        if inicio != -1 and (siguiente is None or inicio < siguiente.start()):
            try:
                datos, i = decodificador.raw_decode(texto, inicio)
            except ValueError:
                pass
        contexto = (datos.get("limit") or {}).get("context")
        gratis = not any((datos.get("cost") or {}).get(k) for k in ("input", "output"))
        modelos.append({
            "id": m.group(1), "nombre": datos.get("name") or m.group(1),
            "detalle": " · ".join(x for x in (f"{contexto // 1000}k de contexto" if contexto else "", "sin costo" if datos and gratis else "") if x),
            "niveles": list((datos.get("variants") or {}).keys()), "nivel_defecto": "",
        })
    if not modelos:
        raise RuntimeError((p.stderr or "opencode no devolvió modelos.").strip()[-300:])
    return modelos


def catalogo(cli: str) -> dict[str, Any]:
    """{disponible, defecto, modelos, detalle} para la interfaz y el doctor."""
    from .modelo import MODELO_CLAUDE_DEFECTO, MODELOS_CLAUDE, modelos_codex

    if cli not in CLIS:
        raise ValueError("CLI no admitida; use " + ", ".join(PROVEEDORES) + ".")
    if not ejecutable(cli):
        return {"disponible": False, "defecto": "", "modelos": [], "detalle": f"{CLIS[cli].nombre} no está instalado (no se encontró «{CLIS[cli].ejecutable}» en PATH)."}
    if cli == "claude":
        return {"disponible": True, "defecto": MODELO_CLAUDE_DEFECTO,
                "modelos": [{**m, "niveles": list(NIVELES_CLASICOS), "nivel_defecto": ""} for m in MODELOS_CLAUDE]}
    fuentes: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "codex": modelos_codex, "agy": catalogo_agy, "grok": catalogo_grok, "opencode": catalogo_opencode}
    try:
        lista = fuentes[cli]()
    except RuntimeError as e:
        return {"disponible": False, "defecto": "", "modelos": [], "detalle": str(e)}
    defecto = next((m["id"] for m in lista if m.get("etiqueta") in ("Por defecto", "Recomendado")), lista[0]["id"])
    return {"disponible": True, "defecto": defecto, "modelos": lista}


# ---------------------------------------------------------------- invocación

def _registrar(uso: Any, etiqueta: str, costo: float | None, entrada: int, salida: int) -> None:
    if uso is not None:
        uso.registrar([etiqueta], costo, entrada, salida)


def invocar_agy(prompt: str, esquema: dict[str, Any], modelo: str, esfuerzo: str, directorio: Path, tiempo: int,
                uso: Any, sistema: str) -> Any:
    exe = ejecutable("agy")
    if not exe:
        raise RuntimeError("No se encontró Antigravity CLI (agy) en PATH.")
    directorio.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rfd-agy-", dir=directorio) as temporal:
        ruta_esquema = Path(temporal) / "esquema.json"
        ruta_esquema.write_text(json.dumps(esquema, ensure_ascii=False), encoding="utf-8")
        # -p no lee stdin y Windows limita la línea de comandos a ~32 000 caracteres: el prompt va como NDJSON.
        mensaje = json.dumps({"event": "user", "message": {"role": "user", "content": f"{sistema}\n\n{prompt}"}}, ensure_ascii=False)
        comando = [exe, "--input-format", "stream-json", "--output-format", "stream-json", "--json-schema", str(ruta_esquema),
                   "--print-timeout", f"{tiempo}s", "--disable-slash-commands", "--sandbox"]
        if modelo.strip():
            comando += ["--model", modelo.strip()]
        if esfuerzo.strip():
            comando += ["--effort", esfuerzo.strip()]
        p = _correr(comando + ["-p="], entrada=mensaje + "\n", tiempo=tiempo + 60, cwd=Path(temporal))
    resultado = None
    for linea in (p.stdout or "").splitlines():
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        if isinstance(evento, dict) and evento.get("event") == "result":
            resultado = evento.get("result") or {}
    if not resultado or resultado.get("status") != "SUCCESS":
        detalle = (resultado or {}).get("error") or (p.stderr or p.stdout or "").strip()[-1200:]
        raise RuntimeError(f"Antigravity falló con el modelo {modelo or 'por defecto'}: {detalle}")
    tokens = resultado.get("usage") or {}
    _registrar(uso, f"agy · {modelo or 'por defecto'}" + (f" · {esfuerzo}" if esfuerzo else ""), None,
               tokens.get("input_tokens", 0), tokens.get("output_tokens", 0) + tokens.get("thinking_tokens", 0))
    datos = resultado.get("structured_output")
    return datos if datos is not None else extraer_json(resultado.get("response", ""))


def invocar_grok(prompt: str, esquema: dict[str, Any], modelo: str, esfuerzo: str, directorio: Path, tiempo: int,
                 uso: Any, sistema: str) -> Any:
    exe = ejecutable("grok")
    if not exe:
        raise RuntimeError("No se encontró Grok CLI (grok) en PATH.")
    directorio.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rfd-grok-", dir=directorio) as temporal:
        ruta = Path(temporal) / "prompt.md"
        ruta.write_text(prompt, encoding="utf-8")
        comando = [exe, "--prompt-file", str(ruta), "--output-format", "json", "--json-schema", json.dumps(esquema, ensure_ascii=False),
                   "--system-prompt-override", sistema, "--no-subagents", "--disable-web-search", "--no-plan",
                   "--cwd", temporal, "--verbatim"]
        if modelo.strip():
            comando += ["-m", modelo.strip()]
        if esfuerzo.strip():
            comando += ["--reasoning-effort", esfuerzo.strip()]
        p = _correr(comando, tiempo=tiempo, cwd=Path(temporal))
    salida = (p.stdout or "").strip()
    if p.returncode != 0 or not salida:
        raise RuntimeError(f"Grok falló con el modelo {modelo or 'por defecto'} (código {p.returncode}). "
                           + (p.stderr or salida).strip()[-1200:])
    respuesta = extraer_json(salida)
    tokens = (respuesta.get("usage") or {}) if isinstance(respuesta, dict) else {}
    _registrar(uso, f"grok · {modelo or 'por defecto'}" + (f" · {esfuerzo}" if esfuerzo else ""),
               respuesta.get("total_cost_usd") if isinstance(respuesta, dict) else None,
               tokens.get("input_tokens", 0) + tokens.get("cache_read_input_tokens", 0),
               tokens.get("output_tokens", 0) + tokens.get("reasoning_tokens", 0))
    if isinstance(respuesta, dict):
        for clave in ("structured_output", "result", "response", "text"):
            valor = respuesta.get(clave)
            if isinstance(valor, dict):
                return valor
            if isinstance(valor, str) and "{" in valor:
                return extraer_json(valor)
    return respuesta


ENTORNO_OPENCODE = {
    # OpenCode lee por compatibilidad ~/.claude/CLAUDE.md, skills externas y la configuración del proyecto.
    "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1", "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1",
    "OPENCODE_DISABLE_SHARE": "1",
}


def invocar_opencode(prompt: str, esquema: dict[str, Any], modelo: str, esfuerzo: str, directorio: Path, tiempo: int,
                     uso: Any, sistema: str) -> Any:
    exe = ejecutable("opencode")
    if not exe:
        raise RuntimeError("No se encontró OpenCode CLI (opencode) en PATH.")
    directorio.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rfd-opencode-", dir=directorio) as temporal:
        comando = [exe, "run", "--format", "json", "--pure", "--dir", temporal]
        if modelo.strip():
            comando += ["-m", modelo.strip()]
        if esfuerzo.strip():
            comando += ["--variant", esfuerzo.strip()]
        # Sin --json-schema: el esquema va en el prompt y la respuesta se valida después.
        p = _correr(comando, entrada=f"{sistema}\n\n{prompt}{instruccion_esquema(esquema)}", tiempo=tiempo, cwd=Path(temporal),
                    env=ENTORNO_OPENCODE)
    textos: list[str] = []
    entrada = salida = 0
    costo = 0.0
    error = ""
    for linea in (p.stdout or "").splitlines():
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        if not isinstance(evento, dict):
            continue
        parte = evento.get("part") or {}
        if evento.get("type") == "text" and parte.get("text"):
            textos.append(parte["text"])
        elif evento.get("type") == "step_finish":
            t = parte.get("tokens") or {}
            entrada += (t.get("input") or 0) + ((t.get("cache") or {}).get("read") or 0)
            salida += (t.get("output") or 0) + (t.get("reasoning") or 0)
            costo += parte.get("cost") or 0
        elif evento.get("type") == "error":
            error = json.dumps(evento.get("error") or evento, ensure_ascii=False)[:600]
    if not textos:
        raise RuntimeError(f"OpenCode falló con el modelo {modelo or 'por defecto'}: "
                           + (error or (p.stderr or p.stdout or "sin respuesta").strip()[-1200:]))
    _registrar(uso, f"opencode · {modelo or 'por defecto'}" + (f" · {esfuerzo}" if esfuerzo else ""), costo or None, entrada, salida)
    return extraer_json("".join(textos))


ADAPTADORES = {"agy": invocar_agy, "grok": invocar_grok, "opencode": invocar_opencode}
