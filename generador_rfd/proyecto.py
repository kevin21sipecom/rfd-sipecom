"""Contexto del sistema existente: inventario de repositorios + CodeGraph (o Repomix).

Sigue el enfoque de soporte-sipecom: CodeGraph indexa la carpeta (init/sync) y aporta el código
relacionado con cada tema del RFD. El inventario determinista describe cada repositorio
(stack, estructura, controladores, servicios, procedimientos) para redactar el AS-IS y las
adecuaciones por componente.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .fuentes import Fuente

MAX_CODIGO = 90_000
IGNORAR = (
    "**/*.dll,**/*.pdb,**/*.exe,**/*.nupkg,**/*.cache,**/bin/**,**/obj/**,"
    "**/packages/**,**/node_modules/**,**/*.min.js,**/*.map,**/.vs/**,**/.codegraph/**"
)
DIRS_IGNORADOS = {".git", ".codegraph", ".vs", "bin", "obj", "node_modules", "packages", "dist", ".angular", "TestResults"}
MARCADORES = ("angular.json", "package.json", ".csproj", ".sln", ".sqlproj", "pom.xml", "requirements.txt", "go.mod")
PIEZAS = [
    ("Controladores", r"Controller\.cs$"),
    ("Componentes Angular", r"\.component\.ts$"),
    ("Servicios", r"(?<!\.spec)\.service\.ts$|Service\.cs$"),
    ("Acceso a datos", r"(Repository|Dao|DAL|Datos)\.cs$"),
]


def _ejecutar(comando: list[str], tiempo: int) -> tuple[int, str]:
    try:
        p = subprocess.run(
            comando, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=tiempo, check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"superó {tiempo} s"
    except OSError as e:
        return 127, str(e)
    return p.returncode, ((p.stdout or "") + "\n" + (p.stderr or "")).strip()


def herramientas() -> dict[str, str | None]:
    return {"codegraph": shutil.which("codegraph"), "repomix": shutil.which("repomix")}


def _preparar_codegraph(cg: str, raiz: str) -> str:
    codigo, salida = _ejecutar([cg, "status", raiz, "--json"], 60)
    try:
        estado = json.loads(salida[salida.find("{"): salida.rfind("}") + 1])
    except ValueError:
        estado = {}
    if not estado.get("initialized"):
        codigo, salida = _ejecutar([cg, "init", raiz, "--yes"], 900)
        if codigo != 0:
            raise RuntimeError(f"codegraph init falló:\n{salida[-1500:]}")
        return "init"
    codigo, salida = _ejecutar([cg, "sync", raiz], 600)
    if codigo != 0:
        raise RuntimeError(f"codegraph sync falló:\n{salida[-1500:]}")
    return "sync"


def _con_codegraph(cg: str, raiz: str, temas: list[str], limite: int) -> str:
    _preparar_codegraph(cg, raiz)
    por_tema = max(3_000, limite // max(1, len(temas)))
    partes = []
    for tema in temas:
        codigo, contexto = _ejecutar([cg, "context", "-p", raiz, "-n", "15", tema], 300)
        if codigo != 0:
            raise RuntimeError(f"codegraph context falló:\n{contexto[-1500:]}")
        partes.append(f"# Código relacionado con: {tema}\n{contexto[:por_tema]}")
    return "\n\n".join(partes)


def _con_repomix(rm: str, raiz: str) -> str:
    with tempfile.TemporaryDirectory(prefix="rfd-repomix-") as temporal:
        destino = Path(temporal) / "repomix.xml"
        codigo, salida = _ejecutar(
            [rm, raiz, "-o", str(destino), "--style", "xml", "--compress", "--ignore", IGNORAR], 600,
        )
        if codigo != 0 or not destino.is_file():
            raise RuntimeError(f"repomix falló:\n{salida[-1500:]}")
        return destino.read_text(encoding="utf-8", errors="replace")


def _es_repositorio(d: Path) -> bool:
    try:
        return (d / ".git").exists() or (d / "README.md").is_file() or any(
            f.is_file() and f.name.endswith(MARCADORES) for f in d.iterdir()
        )
    except OSError:
        return False


def _recorrer(raiz: Path, maximo: int = 40_000) -> list[Path]:
    archivos: list[Path] = []
    for actual, dirs, nombres in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in DIRS_IGNORADOS and not d.startswith(".")]
        archivos += [Path(actual) / n for n in nombres]
        if len(archivos) > maximo:
            break
    return archivos


def _leer(ruta: Path, maximo: int = 200_000) -> str:
    try:
        crudo = ruta.read_bytes()[: maximo * 2]
    except OSError:
        return ""
    # Los scripts de SQL Server suelen guardarse en UTF-16.
    if crudo[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return crudo.decode("utf-16", errors="replace")[:maximo]
    return crudo.decode("utf-8-sig", errors="replace")[:maximo]


def _inventario_repo(repo: Path) -> list[str]:
    archivos = _recorrer(repo)
    rel = [f.relative_to(repo).as_posix() for f in archivos]
    lineas = [f"## Repositorio {repo.name}"]
    codigo, ultimo = _ejecutar(["git", "-c", "i18n.logOutputEncoding=UTF-8", "-C", str(repo), "log", "-1", "--format=%h %ci %s"], 20)
    if codigo == 0 and ultimo:
        lineas.append(f"Último commit: {ultimo.splitlines()[0][:140]}")
    readme = repo / "README.md"
    texto_readme = _leer(readme) if readme.is_file() else ""
    if texto_readme and "TODO: Give a short introduction" not in texto_readme:
        texto = [x.strip() for x in texto_readme.splitlines() if x.strip()]
        lineas += ["README:"] + [f"  {x[:200]}" for x in texto[:10]]
    extensiones = Counter(f.suffix.lower() for f in archivos if f.suffix)
    lineas.append(f"Archivos: {len(archivos)}; por tipo: " + ", ".join(f"{e} {n}" for e, n in extensiones.most_common(8)))
    carpetas = sorted({"/".join(r.split("/")[:2]) for r in rel if r.count("/") >= 2} | {r.split("/")[0] for r in rel if r.count("/") == 1})
    if carpetas:
        lineas.append("Estructura: " + ", ".join(carpetas[:35]))
    for f, r in zip(archivos, rel):
        if f.name.endswith(".csproj"):
            marco = re.search(r"<TargetFramework(?:s|Version)?>([^<]+)<", _leer(f))
            lineas.append(f"Proyecto .NET: {r} ({marco.group(1) if marco else 'framework no declarado'})")
        elif f.name == "angular.json":
            lineas.append(f"Aplicación Angular: {r}")
        elif f.name == "package.json":
            try:
                datos = json.loads(_leer(f))
                deps = {**datos.get("dependencies", {}), **datos.get("devDependencies", {})}
                claves = [f"{k} {v}" for k, v in deps.items() if k in ("@angular/core", "react", "vue", "express", "typescript")]
                lineas.append(f"package.json: {r} {', '.join(claves)}".rstrip())
            except ValueError:
                pass
    for etiqueta, patron in PIEZAS:
        encontrados = sorted({re.sub(patron, "", f.name) for f in archivos if re.search(patron, f.name)})
        if encontrados:
            lineas.append(f"{etiqueta} ({len(encontrados)}): " + ", ".join(encontrados[:45]))
    sql = [f for f in archivos if f.suffix.lower() == ".sql"]
    if sql:
        procedimientos: set[str] = set()
        for f in sql[:3_000]:
            for nombre in re.findall(r"CREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+([\w\[\]\.]+)", _leer(f, 20_000), re.I):
                procedimientos.add(nombre.replace("[", "").replace("]", ""))
        lineas.append(f"SQL: {len(sql)} archivos, {len(procedimientos)} procedimientos almacenados")
        if procedimientos:
            lineas.append("Procedimientos: " + ", ".join(sorted(procedimientos)[:90]))
    if len(archivos) <= 3:
        lineas.append("Observación: la copia local no contiene una implementación funcional.")
    return lineas


def inventario_repositorios(carpeta: Path) -> str:
    """Inventario determinista del sistema existente; admite una carpeta con varios repositorios."""
    carpeta = carpeta.expanduser().resolve()
    subrepos = sorted(d for d in carpeta.iterdir() if d.is_dir() and not d.name.startswith(".") and _es_repositorio(d))
    repos = subrepos if len(subrepos) >= 2 else [carpeta]
    lineas = [f"# Inventario de {carpeta.name}: {len(repos)} repositorio(s)", ", ".join(r.name for r in repos)]
    for repo in repos:
        lineas += [""] + _inventario_repo(repo)
    return "\n".join(lineas)


def _numerar(texto: str, limite: int) -> str:
    numeradas: list[str] = []
    total = 0
    for i, linea in enumerate((x.rstrip() for x in texto.splitlines() if x.strip()), 1):
        fila = f"L{i}: {linea}"
        if total + len(fila) + 1 > limite:
            numeradas.append(f"L{i}: [recortado: el contexto del código excede {limite} caracteres]")
            break
        numeradas.append(fila)
        total += len(fila) + 1
    return "\n".join(numeradas)


def analizar_proyecto(carpeta: Path, temas: str | list[str], limite: int = MAX_CODIGO) -> Fuente:
    """Fuente «codigo»: inventario de repositorios + código relacionado con cada tema."""
    carpeta = carpeta.expanduser().resolve()
    if not carpeta.is_dir():
        raise ValueError(f"La carpeta del proyecto no existe: {carpeta}")
    temas = [temas] if isinstance(temas, str) else temas
    temas = [" ".join(t.split())[:200] for t in temas if t.strip()][:8] or [carpeta.name]
    inventario = inventario_repositorios(carpeta)
    restante = max(5_000, limite - len(inventario))
    h = herramientas()
    if h["codegraph"]:
        codigo, origen = _con_codegraph(h["codegraph"], str(carpeta), temas, restante), "CodeGraph"
    elif h["repomix"]:
        codigo, origen = _con_repomix(h["repomix"], str(carpeta))[:restante], "Repomix"
    else:
        codigo, origen = "(CodeGraph y Repomix no están instalados: sólo se incluye el inventario.)", "inventario"
    return Fuente("", f"Repositorios del proyecto {carpeta.name} ({origen})", "codigo",
                  _numerar(inventario + "\n\n" + codigo, limite))
