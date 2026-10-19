"""Comandos públicos del generador de RFD."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from .modelo import MODELO_CLAUDE_DEFECTO, MODELOS_CLAUDE
from .motores import CLIS, catalogo, ejecutable
from .pipeline import LINEAMIENTOS, PLANTILLA, RAIZ, Opciones, Resultado, generar, publicar
from .proyecto import herramientas

PROVEEDORES = list(CLIS)


def _mostrar(r: Resultado) -> None:
    print(f"RFD Word: {r.salida}")
    print(f"Datos JSON: {r.salida.with_suffix('.json')}")
    print(f"Revisión: {r.salida.with_suffix('.revision.md')}")
    if r.revision_word and r.revision_word.get("pdf"):
        print(f"PDF: {r.revision_word['pdf']} ({r.revision_word.get('paginas')} páginas)")
    if r.uso:
        print(f"Modelo: {', '.join(r.uso['modelos'])} · {r.uso['llamadas']} llamada(s) · costo {r.uso['costo_usd']}")
    print(f"Hallazgos: {len(r.hallazgos)}")


def _doctor(proveedor: str, modelo: str | None) -> None:
    """Comprobaciones headless, como el ToolDoctor de common-ts: ejecutable, sesión (Codex) y catálogo de modelos."""
    sys.stdout.reconfigure(encoding="utf-8")
    for c in CLIS.values():
        print(f"{c.nombre:<12} ({c.id}): {ejecutable(c.id) or 'NO ENCONTRADO'}")
    print(f"Plantilla: {'OK' if PLANTILLA.is_file() else 'NO ENCONTRADA'} ({PLANTILLA})")
    print(f"Lineamientos: {'OK' if LINEAMIENTOS.is_file() else 'NO ENCONTRADOS'}")
    for nombre, ruta in herramientas().items():
        print(f"{nombre}: {ruta or 'no instalado (opcional, para --proyecto)'}")
    if proveedor == "codex" and ejecutable("codex"):
        for etiqueta, args in [("versión", ["--version"]), ("sesión", ["login", "status"])]:
            try:
                p = subprocess.run([ejecutable("codex") or "codex", *args], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=20, check=False, stdin=subprocess.DEVNULL)
                linea = next((x.strip() for x in ((p.stdout or "") + (p.stderr or "")).splitlines() if x.strip()), "sin respuesta")
            except subprocess.TimeoutExpired:
                linea = "no respondió (puede requerir una sesión interactiva)"
            print(f"Codex {etiqueta}: {linea}")
    c = CLIS[proveedor]
    print(f"\n{c.nombre}: {c.reglas}")
    datos = catalogo(proveedor)
    if not datos["disponible"]:
        print(f"Modelos: {datos.get('detalle')}")
        return
    print("Modelos (use --modelo y, opcionalmente, --esfuerzo):")
    for m in datos["modelos"]:
        marca = " (por defecto)" if m["id"] == datos["defecto"] else ""
        niveles = f" [{', '.join(m.get('niveles') or [])}]" if m.get("niveles") else ""
        print(f"  {m['id']:<34} {m['nombre']}{marca}{niveles}")
    if modelo and modelo not in {m["id"] for m in datos["modelos"]}:
        print(f"Aviso: el modelo «{modelo}» no figura en el catálogo de {c.nombre}.")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="generador-rfd", description="Genera RFD Word SIPECOM con Claude Code, Codex, Antigravity, Grok u OpenCode.")
    sub = p.add_subparsers(dest="comando", required=True)
    w = sub.add_parser("gui", help="Abre la interfaz web local (http://127.0.0.1:2122).")
    w.add_argument("--puerto", type=int, default=2122)
    w.add_argument("--sin-navegador", action="store_true", help="No abrir el navegador automáticamente.")
    d = sub.add_parser("doctor", help="Comprueba las CLIs, la plantilla, CodeGraph y el catálogo de modelos de una CLI.")
    d.add_argument("--proveedor", choices=PROVEEDORES, default="claude")
    d.add_argument("--modelo")
    g = sub.add_parser("generar", help="Extrae fuentes, llama al modelo y genera el RFD.")
    g.add_argument("--transcripcion", type=Path, action="append", default=[], help="Opcional si se indica al menos un --contexto.")
    g.add_argument("--contexto", type=Path, action="append", default=[])
    g.add_argument("--estilo", type=Path, action="append", default=[], help="RFD de referencia: sólo se imita su redacción y estructura.")
    g.add_argument("--proyecto", type=Path, help="Carpeta del código existente (uno o varios repositorios).")
    g.add_argument("--enfoque", default="", help="Tema para buscar en el código; por defecto, los temas detectados en cada documento.")
    g.add_argument("--cliente", required=True)
    g.add_argument("--codigo", required=True)
    g.add_argument("--tipo-proyecto", choices=["nuevo", "existente"], required=True)
    g.add_argument("--titulo")
    g.add_argument("--fecha", default=date.today().strftime("%d/%m/%Y"))
    g.add_argument("--proveedor", choices=PROVEEDORES, default="claude", help="CLI de IA: " + ", ".join(f"{c.id} ({c.nombre})" for c in CLIS.values()) + ".")
    g.add_argument("--modelo", default="", help="Con claude: " + ", ".join(m["id"] for m in MODELOS_CLAUDE) + " o un alias; por defecto " + MODELO_CLAUDE_DEFECTO + ". Otras CLIs: vea `generador-rfd doctor --proveedor <cli>`.")
    g.add_argument("--salida", type=Path, required=True)
    g.add_argument("--plantilla", type=Path, default=PLANTILLA)
    g.add_argument("--publico", action="store_true")
    g.add_argument("--esfuerzo", default="", help="Nivel de razonamiento de la CLI (low, medium, high, xhigh, max; en opencode, la variante del modelo). Vacío: el del modelo.")
    g.add_argument("--sin-word", action="store_true", help="No abrir Microsoft Word para actualizar el índice ni exportar PDF.")
    c = sub.add_parser("contexto-codigo", help="Muestra el contexto que CodeGraph/Repomix aporta de un proyecto, sin llamar al modelo.")
    c.add_argument("--proyecto", type=Path, required=True)
    c.add_argument("--enfoque", required=True)
    r = sub.add_parser("renderizar", help="Genera Word desde un JSON validado, sin llamar al modelo.")
    r.add_argument("--datos", type=Path, required=True)
    r.add_argument("--salida", type=Path, required=True)
    r.add_argument("--plantilla", type=Path, default=PLANTILLA)
    r.add_argument("--publico", action="store_true")
    r.add_argument("--con-word", action="store_true", help="Actualizar índice y exportar PDF con Microsoft Word.")
    sub.add_parser("historial", help="Lista los RFD guardados en la base de datos (datos/rfd.db) y sus preguntas abiertas.")
    m = sub.add_parser("mejorar", help="Adapta un RFD guardado a las respuestas del cliente y crea la versión siguiente.")
    m.add_argument("--id", type=int, required=True, help="ID del RFD en el historial (vea `generador-rfd historial`).")
    m.add_argument("--cuestionario", type=Path, action="append", default=[], help="Cuestionario .docx respondido por el cliente.")
    m.add_argument("--adjunto", type=Path, action="append", default=[], help="Acta, correo o aclaración del cliente (.txt, .md, .docx, .pptx, .pdf, .xlsx).")
    m.add_argument("--proveedor", choices=PROVEEDORES, default="claude")
    m.add_argument("--modelo", default="")
    m.add_argument("--esfuerzo", default="")
    m.add_argument("--sin-word", action="store_true")
    rg = sub.add_parser("reglas", help="Lista, agrega, activa o elimina reglas del equipo que se inyectan al modelo.")
    rg.add_argument("--agregar", metavar="TEXTO", help="Texto de la regla, p. ej. «No usar etc. ni entre otros».")
    rg.add_argument("--tipo", choices=["evitar", "exigir"], default="evitar")
    rg.add_argument("--seccion", default="todo", help="todo, requerimientos, criterios, flujo, esfuerzo, preguntas…")
    rg.add_argument("--patron", default="", help="Verificación automática: términos con | o una expresión con re:")
    rg.add_argument("--cliente", default="", help="Sólo para este cliente; vacío: todos.")
    rg.add_argument("--activar", type=int, metavar="ID")
    rg.add_argument("--desactivar", type=int, metavar="ID")
    rg.add_argument("--eliminar", type=int, metavar="ID")
    return p


def _reglas(a: argparse.Namespace) -> None:
    from .reglas import SECCIONES, Regla
    from .servidor import almacen

    sys.stdout.reconfigure(encoding="utf-8")
    db = almacen()
    if a.agregar:
        r = db.guardar_regla(Regla(texto=a.agregar, tipo=a.tipo, seccion=a.seccion, patron=a.patron, cliente=a.cliente))
        print(f"Regla R{r.id} guardada.")
    for regla_id, activa in ((a.activar, True), (a.desactivar, False)):
        if regla_id is not None:
            r = next((x for x in db.reglas() if x.id == regla_id), None)
            if r is None:
                raise ValueError(f"No existe la regla R{regla_id}.")
            r.activa = activa
            db.guardar_regla(r)
    if a.eliminar is not None:
        db.eliminar_regla(a.eliminar)
    for r in db.reglas():
        estado = "activa" if r.activa else "inactiva"
        print(f"R{r.id:<4} {r.tipo:<7} {SECCIONES[r.seccion]:<26} {r.cliente or 'todos':<14} {estado:<9} {r.texto}"
              + (f"  [verifica: {r.patron}]" if r.patron else ""))


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        if a.comando == "gui":
            from .servidor import iniciar
            iniciar(a.puerto, not a.sin_navegador)
        elif a.comando == "doctor":
            _doctor(a.proveedor, a.modelo)
        elif a.comando == "generar":
            def progreso(paso: str, detalle: str) -> None:
                print(f"[{paso}] {detalle}", flush=True)

            from .servidor import almacen

            _mostrar(generar(Opciones(
                transcripciones=a.transcripcion, contextos=a.contexto, estilos=a.estilo, proyecto=a.proyecto,
                enfoque=a.enfoque, cliente=a.cliente, codigo=a.codigo, tipo_proyecto=a.tipo_proyecto,
                titulo=a.titulo, fecha=a.fecha, proveedor=a.proveedor, modelo=a.modelo, salida=a.salida,
                plantilla=a.plantilla, publico=a.publico, revisar_word=not a.sin_word, esfuerzo=a.esfuerzo,
                reglas=almacen().reglas_para(a.cliente),
            ), progreso))
        elif a.comando == "reglas":
            _reglas(a)
        elif a.comando == "contexto-codigo":
            from .proyecto import analizar_proyecto
            fuente = analizar_proyecto(a.proyecto, a.enfoque)
            sys.stdout.reconfigure(encoding="utf-8")
            print(fuente.para_prompt())
        elif a.comando == "renderizar":
            datos = json.loads(a.datos.read_text(encoding="utf-8-sig"))
            _mostrar(publicar(datos, a.salida, a.plantilla, a.publico, revisar_word=a.con_word))
        elif a.comando == "historial":
            from .servidor import almacen
            sys.stdout.reconfigure(encoding="utf-8")
            for r in almacen().listar():
                calidad = f"{r['calidad']:.0%}" if r["calidad"] is not None else "—"
                print(f"{r['id']:>4}  {r['codigo']:<14} v{r['version']:<5} {r['respondidas']:>2}/{r['preguntas']:<2} resp.  "
                      f"calidad {calidad:<5} {r['archivo'] or ''}{'  (mejorado)' if r['mejorado'] else ''}")
        elif a.comando == "mejorar":
            from .cuestionario import leer_cuestionario
            from .pipeline import OpcionesMejora, mejorar
            from .servidor import SALIDAS, _registrar, almacen

            base = almacen().obtener(a.id)
            for c in a.cuestionario:
                print(f"Cuestionario {c.name}: {almacen().responder_varias(a.id, leer_cuestionario(c))} respuesta(s) guardada(s)")
            o = OpcionesMejora(
                base=Path(base["ruta_docx"]), salida_dir=SALIDAS, respuestas=almacen().respuestas(a.id), adjuntos=a.adjunto,
                proveedor=a.proveedor, modelo=a.modelo or (MODELO_CLAUDE_DEFECTO if a.proveedor == "claude" else ""),
                esfuerzo=a.esfuerzo, revisar_word=not a.sin_word, datos_base=base["datos"], analisis_base=base["analisis"],
                reglas=almacen().reglas_para(base["cliente"]),
            )
            r = mejorar(o, lambda paso, detalle: print(f"[{paso}] {detalle}", flush=True))
            nuevo = _registrar(r, "mejorado", o.proveedor, o.modelo, padre_id=a.id)
            _mostrar(r)
            print(f"Versión {r.datos['version']} registrada con ID {nuevo}; {len(r.datos['cambios'])} cambio(s), "
                  f"{len(r.datos['preguntas_cliente'])} pregunta(s) abiertas.")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

