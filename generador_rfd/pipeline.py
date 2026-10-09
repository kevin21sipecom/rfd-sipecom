"""Flujo completo de generación de un RFD.

1. Lectura de fuentes (transcripciones, contexto) y referencias de estilo.
2. Análisis estructurado de cada fuente con el modelo (en paralelo).
3. Inventario de repositorios y código relacionado con los temas detectados (CodeGraph).
4. Redacción del RFD con análisis + fuentes completas + sistema existente + estilo.
5. Armado del Word con la plantilla SIPECOM.
6. Revisión: Word actualiza el índice y exporta PDF; se buscan páginas vacías,
   instrucciones de plantilla y contenido heredado de las referencias de estilo.
"""

from __future__ import annotations

import json
from datetime import date
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .fuentes import Fuente, cargar_fuentes, leer_documento, limite_para
from .calidad import UMBRAL, Evaluacion, evaluar, instrucciones_correccion
from .reglas import Regla, bloque_prompt, incumplidas
from .modelo import Uso, adaptar_rfd, analizar_fuentes, corregir_rfd, reconstruir_rfd, redactar_rfd, temas_de_codigo
from .schema import Hallazgo, auditar_contenido, auditar_texto_final, normalizar, validar_estructura
from .word import crear_docx, texto_docx

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = RAIZ / "plantillas" / "Plantilla_RFD_SIPECOM.docx"
LINEAMIENTOS = RAIZ / "LINEAMIENTOS_RFD.md"

Progreso = Callable[[str, str], None]


@dataclass
class Opciones:
    transcripciones: list[Path]
    contextos: list[Path]
    cliente: str
    codigo: str
    tipo_proyecto: str
    fecha: str
    salida: Path
    proveedor: str = "claude"
    modelo: str = ""
    esfuerzo: str = ""
    titulo: str | None = None
    estilos: list[Path] = field(default_factory=list)
    proyecto: Path | None = None
    enfoque: str = ""
    publico: bool = False
    revisar_word: bool = True
    rondas_calidad: int = 2
    plantilla: Path = PLANTILLA
    reglas: list[Regla] = field(default_factory=list)   # reglas del equipo activas para este cliente


@dataclass
class Resultado:
    datos: dict[str, Any]
    hallazgos: list[Hallazgo]
    salida: Path
    fuentes: list[Fuente]
    uso: dict[str, Any] | None = None
    revision_word: dict[str, Any] | None = None
    calidad: dict[str, Any] | None = None


GENERICOS = {
    "Capítulo", "Requerimiento", "Requerimientos", "Funcional", "Detallado", "Justificación", "Objetivo", "Alcance",
    "Proceso", "Flujo", "Criterios", "Cliente", "Usuario", "Sistema", "Portal", "Restricciones", "Entregables",
    "Esfuerzo", "Firmas", "Anexos", "Prerrequisitos", "Descripción", "Análisis", "Diseño", "Construcción", "Pruebas",
    "Implementación", "Cierre", "SIPECOM", "Pendiente", "Nombre", "Fecha", "Versión", "Cargo", "Revisor", "Aprobación",
}


def terminos_ajenos(fuentes: list[Fuente], cliente: str) -> list[str]:
    """Nombres propios frecuentes en las referencias de estilo que no aparecen en las fuentes reales."""
    estilo = " ".join(f.contenido for f in fuentes if f.categoria == "estilo")
    if not estilo:
        return []
    propio = (" ".join(f.contenido for f in fuentes if f.categoria != "estilo") + " " + cliente).lower()
    # Una palabra que también aparece en minúsculas es un término común, no un nombre propio.
    comunes = set(re.findall(r"\b[a-záéíóúñ][\wáéíóúñ]{3,}\b", estilo))
    candidatos: dict[str, int] = {}
    for palabra in re.findall(r"\b[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]{3,}\b", estilo):
        if palabra not in GENERICOS and palabra.lower() not in comunes:
            candidatos[palabra] = candidatos.get(palabra, 0) + 1
    return sorted(p for p, n in candidatos.items() if n >= 2 and p.lower() not in propio)[:60]


def escribir_informe(datos: dict, hallazgos: list[Hallazgo], ruta: Path, uso: dict | None = None,
                     revision_word: dict | None = None, fuentes: list[Fuente] | None = None,
                     calidad: dict | None = None) -> None:
    lineas = [
        "# Revisión del RFD", "",
        f"- Código: {datos['codigo']}",
        f"- Título: {datos['titulo']}",
        f"- Cliente: {datos['cliente']}",
        f"- Tipo de proyecto: {datos['tipo_proyecto']}",
        f"- Hallazgos: {len(hallazgos)}",
    ]
    if uso:
        costo = f"{uso['costo_usd']:.3f} USD" if uso.get("costo_usd") is not None else "no informado"
        tokens = f"{uso.get('tokens_entrada', 0):,} tokens de entrada y {uso.get('tokens_salida', 0):,} de salida"
        lineas.append(f"- Modelo: {', '.join(uso.get('modelos') or [])} · {uso.get('llamadas', 0)} llamada(s) · {tokens} · costo {costo}")
    if revision_word:
        if revision_word.get("ok"):
            lineas.append(f"- Word: índice actualizado, {revision_word.get('paginas')} páginas, PDF {'generado' if revision_word.get('pdf') else 'no generado'}")
        else:
            lineas.append(f"- Word: revisión no realizada ({revision_word.get('motivo')})")
    if calidad:
        aprobados = sum(c["ok"] for c in calidad["criterios"])
        lineas.append(f"- Calidad narrativa: {calidad['puntaje']:.0%} ({aprobados}/{len(calidad['criterios'])} criterios; "
                      f"umbral {calidad['umbral']:.0%}; rondas de corrección: {calidad.get('rondas', 0)})")
    lineas += ["", "## Hallazgos", ""]
    lineas += [f"- **{h.codigo}:** {h.mensaje}" for h in hallazgos] or ["- Sin hallazgos automáticos."]
    if calidad:
        lineas += ["", "## Nivel narrativo (rúbrica del RFD de referencia)", ""]
        lineas += [f"- {'✔' if c['ok'] else '✘'} **{c['id']}:** {c['descripcion']}" + (f" — {c['detalle']}" if c["detalle"] else "")
                   for c in calidad["criterios"]]
    if calidad and calidad.get("reglas"):
        lineas += ["", "## Reglas del equipo aplicadas", ""]
        lineas += [f"- R{r['id']} ({r['tipo']}, {r['seccion']}{', ' + r['cliente'] if r['cliente'] else ''}): {r['texto']}"
                   + (f" · verificación: `{r['patron']}`" if r["patron"] else " · sólo instrucción") for r in calidad["reglas"]]
    lineas += ["", "## Definiciones requeridas antes de construir", ""]
    lineas += [f"- **{x['id']} {x['titulo']}:** {x['descripcion']} ({', '.join(x['evidencias']) or 'sin evidencia'})"
               for x in datos["definiciones"]] or ["- Ninguna registrada."]
    lineas += ["", "## Preguntas para el cliente", ""]
    lineas += [f"- **{x['id']} {x['tema']}:** {x['contexto']} {x['pregunta']}" for x in datos.get("preguntas_cliente", [])] or ["- Ninguna abierta."]
    if datos.get("cambios"):
        lineas += ["", f"## Cambios de la versión {datos.get('version', '')}", ""]
        lineas += [f"- **{c['pregunta']}** · {c['seccion']}: {c['cambio']}" for c in datos["cambios"]]
    lineas += ["", "## Supuestos", ""]
    lineas += [f"- {s}" for s in datos["supuestos"]] or ["- Ninguno registrado."]
    lineas += ["", "## Preguntas pendientes", ""]
    lineas += [f"- **{p['pregunta']}** Motivo: {p['motivo']}" for p in datos["pendientes"]] or ["- Ninguna registrada."]
    lineas += ["", "## Trazabilidad de requisitos", ""]
    for r in datos["requerimientos"]:
        refs = ", ".join(r["evidencias"]) if r["evidencias"] else "Sin evidencia"
        lineas.append(f"- {r['id']} {r['nombre']}: {refs}")
    if fuentes:
        lineas += ["", "## Fuentes", ""]
        lineas += [f"- {f.id} ({f.categoria}) {f.nombre}: {len(f.contenido):,} caracteres" for f in fuentes]
    lineas += ["", "Revisión automática. Una persona responsable debe validar el contenido y el Word antes de distribuirlo.", ""]
    ruta.write_text("\n".join(lineas), encoding="utf-8")


def publicar(datos: dict, salida: Path, plantilla: Path = PLANTILLA, publico: bool = False, *,
             revisar_word: bool = False, terminos: list[str] | None = None, uso: dict | None = None,
             fuentes: list[Fuente] | None = None, progreso: Progreso | None = None,
             calidad: dict | None = None, extra_hallazgos: list[Hallazgo] | None = None) -> Resultado:
    """Valida, arma el Word, lo revisa y escribe JSON, cuestionario e informe. Devuelve hallazgos y revisión."""
    normalizar(datos)
    validar_estructura(datos)
    salida = salida.expanduser().resolve()
    if salida.suffix.lower() != ".docx":
        raise ValueError("La salida debe terminar en .docx.")
    salida.parent.mkdir(parents=True, exist_ok=True)
    hallazgos = auditar_contenido(datos)
    informe = salida.with_suffix(".revision.md")
    if publico and hallazgos:
        escribir_informe(datos, hallazgos, informe, uso, None, fuentes, calidad)
        raise ValueError(f"El modo público exige resolver {len(hallazgos)} hallazgo(s). Revise {informe}.")
    if progreso:
        progreso("word", "Armando el Word con la plantilla SIPECOM")
    crear_docx(datos, plantilla.expanduser().resolve(), salida)
    salida.with_suffix(".json").write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from .cuestionario import crear_cuestionario

    cuestionario = salida.with_suffix(".cuestionario.docx")
    if not crear_cuestionario(datos, cuestionario) and cuestionario.is_file():
        cuestionario.unlink()
    revision = None
    if revisar_word:
        if progreso:
            progreso("revision", "Microsoft Word actualiza el índice y exporta el PDF")
        from .revision import revisar_con_word

        revision = revisar_con_word(salida)
        for pagina in (revision.get("vacias") or []) if revision.get("ok") else []:
            hallazgos.append(Hallazgo("pagina_vacia", f"La página {pagina} quedó vacía."))
    vocabulario_plantilla = texto_docx(plantilla.expanduser().resolve()).lower()
    terminos = [t for t in terminos or [] if t.lower() not in vocabulario_plantilla]
    hallazgos += auditar_texto_final(texto_docx(salida), terminos)
    hallazgos += extra_hallazgos or []
    if calidad and calidad["puntaje"] < calidad["umbral"]:
        hallazgos.append(Hallazgo("calidad_narrativa", f"El nivel narrativo es {calidad['puntaje']:.0%}; "
                                  f"el umbral de la referencia es {calidad['umbral']:.0%}."))
    escribir_informe(datos, hallazgos, informe, uso, revision, fuentes, calidad)
    return Resultado(datos, hallazgos, salida, fuentes or [], uso, revision, calidad)


def generar(o: Opciones, progreso: Progreso | None = None) -> Resultado:
    avisar = progreso or (lambda paso, detalle: None)
    directorio = o.salida.expanduser().resolve().parent
    avisar("fuentes", "Leyendo transcripciones, contexto y referencias de estilo")
    fuentes = cargar_fuentes(o.transcripciones, o.contextos, o.estilos, limite_para(o.proveedor))
    uso = Uso()

    avisar("analisis", "Analizando cada documento")
    analisis = analizar_fuentes(
        fuentes, cliente=o.cliente, proveedor=o.proveedor, modelo=o.modelo, directorio=directorio, uso=uso, esfuerzo=o.esfuerzo,
        progreso=lambda hechos, total, nombre: avisar("analisis", f"Analizando documentos ({hechos}/{total}): {nombre}"),
    )
    (directorio / f"{o.salida.stem}.analisis.json").write_text(
        json.dumps({f.id: {"nombre": f.nombre, **analisis.get(f.id, {})} for f in fuentes if f.id in analisis},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if o.proyecto is not None:
        from .proyecto import analizar_proyecto

        temas = temas_de_codigo(analisis, o.titulo, o.enfoque)
        avisar("codigo", f"Inventario de repositorios y CodeGraph: {', '.join(temas)[:160]}")
        restante = limite_para(o.proveedor) - sum(len(f.contenido) for f in fuentes) - 40_000
        if restante < 5_000:
            raise ValueError("No queda espacio para el contexto del código; reduzca los documentos.")
        codigo = analizar_proyecto(o.proyecto, temas, min(90_000, restante))
        n = sum(1 for f in fuentes if f.categoria != "estilo") + 1
        fuentes.insert(n - 1, Fuente(f"F{n:02}", codigo.nombre, codigo.categoria, codigo.contenido))

    avisar("modelo", "Redactando el RFD")
    datos = redactar_rfd(
        fuentes=fuentes, lineamientos=LINEAMIENTOS.read_text(encoding="utf-8"), cliente=o.cliente, codigo=o.codigo,
        tipo_proyecto=o.tipo_proyecto, fecha=o.fecha, titulo=o.titulo, proveedor=o.proveedor, modelo=o.modelo,
        directorio_salida=directorio, analisis=analisis, uso=uso, esfuerzo=o.esfuerzo, reglas=bloque_prompt(o.reglas),
    )
    datos, calidad = asegurar_calidad(datos, o, analisis, uso, directorio, avisar)
    return publicar(datos, o.salida, o.plantilla, o.publico, revisar_word=o.revisar_word,
                    terminos=terminos_ajenos(fuentes, o.cliente), uso=uso.como_dict(), fuentes=fuentes, progreso=avisar,
                    calidad=calidad, extra_hallazgos=hallazgos_reglas(datos, o.reglas))


def hallazgos_reglas(datos: dict, reglas: list[Regla]) -> list[Hallazgo]:
    return [Hallazgo("regla_incumplida", f"{r.etiqueta} «{r.texto}»: {detalle}") for r, detalle in incumplidas(datos, reglas)]


def asegurar_calidad(datos: dict, o: Any, analisis: dict[str, dict[str, Any]] | None, uso: Uso, directorio: Path,
                     avisar: Progreso, con_codigo: bool | None = None) -> tuple[dict, dict]:
    """Evalúa el nivel narrativo y pide al mismo motor corregir sólo lo que no cumple; conserva la mejor versión."""
    con_codigo = (getattr(o, "proyecto", None) is not None) if con_codigo is None else con_codigo
    reglas: list[Regla] = getattr(o, "reglas", [])
    mejor, ev = datos, evaluar(datos, analisis, con_codigo, reglas)
    rondas = 0
    while not ev.aprobado() and rondas < o.rondas_calidad:
        rondas += 1
        avisar("calidad", f"Revisión editorial {rondas}/{o.rondas_calidad}: nivel {ev.puntaje:.0%}, "
                          f"{len(ev.fallas)} criterio(s) por corregir")
        try:
            candidato = corregir_rfd(datos=mejor, fallas=instrucciones_correccion(ev), analisis=analisis,
                                     proveedor=o.proveedor, modelo=o.modelo, directorio_salida=directorio,
                                     uso=uso, esfuerzo=o.esfuerzo, reglas=bloque_prompt(reglas))
        except (RuntimeError, ValueError) as e:
            avisar("calidad", f"La revisión editorial no se aplicó: {str(e)[:160]}")
            break
        candidato.update({k: mejor[k] for k in ("version", "historial") if k in mejor})
        nueva: Evaluacion = evaluar(candidato, analisis, con_codigo, reglas)
        if nueva.puntaje >= ev.puntaje:
            mejor, ev = candidato, nueva
    avisar("calidad", f"Nivel narrativo {ev.puntaje:.0%} (umbral {UMBRAL:.0%})")
    return mejor, {**ev.como_dict(), "rondas": rondas, "reglas": [r.como_dict() for r in reglas if r.activa]}


# ---------------------------------------------------------------- Mejorar un RFD con respuestas del cliente

@dataclass
class OpcionesMejora:
    base: Path
    salida_dir: Path
    respuestas: dict[str, str] = field(default_factory=dict)
    cuestionarios: list[Path] = field(default_factory=list)
    adjuntos: list[Path] = field(default_factory=list)
    proveedor: str = "claude"
    modelo: str = ""
    esfuerzo: str = ""
    cliente: str = ""
    codigo: str = ""
    tipo_proyecto: str = "existente"
    revisar_word: bool = True
    rondas_calidad: int = 2
    plantilla: Path = PLANTILLA
    datos_base: dict[str, Any] | None = None      # RFD del historial (SQLite): evita volver a cargar archivos
    analisis_base: dict[str, Any] | None = None
    reglas: list[Regla] = field(default_factory=list)


def siguiente_version(version: str) -> str:
    try:
        mayor, menor = (version or "0.1").split(".")[:2]
        return f"{int(mayor)}.{int(menor) + 1}"
    except ValueError:
        return "0.2"


def _portada(texto: str) -> dict[str, str]:
    lineas = [x.strip() for x in texto.splitlines() if x.strip()]
    codigo = next((m.group(1) for x in lineas[:12] if (m := re.fullmatch(r"\(([^)]+)\)", x))), "")
    i = next((k for k, x in enumerate(lineas[:12]) if x == f"({codigo})"), -1)
    return {"codigo": codigo, "titulo": lineas[i + 1] if i >= 0 else "", "cliente": lineas[i + 2] if i >= 0 else ""}


def cargar_base(o: OpcionesMejora, uso: Uso, avisar: Progreso) -> dict[str, Any]:
    if o.datos_base is not None:
        return normalizar(json.loads(json.dumps(o.datos_base)))
    base = o.base.expanduser().resolve()
    if base.suffix.lower() == ".json":
        return normalizar(json.loads(base.read_text(encoding="utf-8-sig")))
    if base.suffix.lower() != ".docx":
        raise ValueError("El RFD base debe ser el .json generado o un .docx del RFD.")
    texto = texto_docx(base)
    portada = _portada(texto)
    avisar("base", "Reconstruyendo la estructura del RFD desde el Word")
    datos = reconstruir_rfd(
        texto=texto, cliente=o.cliente or portada["cliente"].title() or "Cliente", codigo=o.codigo or portada["codigo"] or "RFD",
        tipo_proyecto=o.tipo_proyecto, fecha=date.today().strftime("%d/%m/%Y"), proveedor=o.proveedor, modelo=o.modelo,
        directorio_salida=o.salida_dir, uso=uso, esfuerzo=o.esfuerzo,
    )
    return normalizar(datos)


def mejorar(o: OpcionesMejora, progreso: Progreso | None = None) -> Resultado:
    """Adapta un RFD existente a las respuestas del cliente sin rehacerlo; sube la versión y registra los cambios."""
    avisar = progreso or (lambda paso, detalle: None)
    uso = Uso()
    avisar("base", "Cargando el RFD base")
    base = cargar_base(o, uso, avisar)

    avisar("respuestas", "Reuniendo las respuestas del cliente")
    from .cuestionario import leer_cuestionario

    respuestas = dict(o.respuestas)
    for c in o.cuestionarios:
        for id_, texto in leer_cuestionario(c).items():
            respuestas.setdefault(id_, texto)
    respuestas = {k: v.strip() for k, v in respuestas.items() if v and v.strip()}
    preguntas = {p["id"]: p for p in base.get("preguntas_cliente", [])}
    lista = [{"id": k, "tema": preguntas.get(k, {}).get("tema", ""), "pregunta": preguntas.get(k, {}).get("pregunta", ""),
              "respuesta": v} for k, v in sorted(respuestas.items())]
    adjuntos = [Fuente(f"R{i:02}", r.name, "respuesta", leer_documento(r)) for i, r in enumerate(o.adjuntos, 1)]
    if not lista and not adjuntos:
        raise ValueError("No hay respuestas: escriba al menos una, cargue el cuestionario respondido o un documento del cliente.")

    avisar("modelo", f"Adaptando el RFD con {len(lista)} respuesta(s) y {len(adjuntos)} documento(s)")
    nuevo = adaptar_rfd(datos=base, respuestas=lista, adjuntos=adjuntos, proveedor=o.proveedor, modelo=o.modelo,
                        directorio_salida=o.salida_dir, uso=uso, esfuerzo=o.esfuerzo, reglas=bloque_prompt(o.reglas))
    version = siguiente_version(base.get("version", "0.1"))
    nuevo["version"] = version
    nuevo["historial"] = base.get("historial", []) + [{
        "version": version, "fecha": date.today().strftime("%d/%m/%Y"),
        "descripcion": "Incorporación de respuestas del cliente" + (f" ({', '.join(r['id'] for r in lista[:8])}{'…' if len(lista) > 8 else ''})" if lista else ""),
    }]

    extra: list[Hallazgo] = []
    mencionadas = " ".join(c["pregunta"] + " " + c["cambio"] for c in nuevo["cambios"])
    for r in lista:
        if r["id"] not in mencionadas:
            extra.append(Hallazgo("respuesta_sin_incorporar", f"La respuesta a {r['id']} no figura en el registro de cambios."))
    eliminados = sorted({x["id"] for x in base["requerimientos"]} - {x["id"] for x in nuevo["requerimientos"]})
    if eliminados:
        extra.append(Hallazgo("rf_eliminado", f"La adaptación eliminó {', '.join(eliminados)}; verifique que el cliente lo pidió."))

    stem = re.sub(r"(_v\d+\.\d+)?(_editado)?$", "", o.base.stem)
    ruta_analisis = o.base.with_name(f"{stem}.analisis.json")
    analisis = o.analisis_base or (json.loads(ruta_analisis.read_text(encoding="utf-8")) if ruta_analisis.is_file() else None)
    con_codigo = any(c["ubicacion"].strip() for c in nuevo["componentes"]["items"])
    nuevo, calidad = asegurar_calidad(nuevo, o, analisis, uso, o.salida_dir, avisar, con_codigo)
    extra += hallazgos_reglas(nuevo, o.reglas)

    salida = o.salida_dir / f"{stem}_v{version}.docx"
    salida.with_suffix(".respuestas.json").parent.mkdir(parents=True, exist_ok=True)
    salida.with_suffix(".respuestas.json").write_text(
        json.dumps({"base": str(o.base), "respuestas": lista, "adjuntos": [a.nombre for a in adjuntos]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    if analisis:
        salida.with_suffix(".analisis.json").write_text(json.dumps(analisis, ensure_ascii=False, indent=2), encoding="utf-8")
    return publicar(nuevo, salida, o.plantilla, False, revisar_word=o.revisar_word, uso=uso.como_dict(),
                    fuentes=adjuntos, progreso=avisar, calidad=calidad, extra_hallazgos=extra)
