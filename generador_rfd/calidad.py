"""Rúbrica de nivel narrativo calibrada con el RFD de referencia aprobado (integración de un portal de clientes con SAP S/4HANA).

Los umbrales salen de medir ese documento sección por sección: párrafos de 25-110 palabras,
criterios de aceptación de ~20-30 palabras en voz normativa («deberá»), una línea de referencia
funcional por interfaz, flujos de 4-8 pasos, definiciones con evidencia de varias fuentes, etc.
Se aplica igual a cualquier motor (Claude, Codex o modelos locales).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from .reglas import SECCIONES, Regla, verificar

UMBRAL = 0.85
NORMATIVO = re.compile(r"\b(deber[áa]n?|no deber[áa]n?|se (?:deber[áa]|adecuar[áa]|utilizar[áa]|incorporar[áa]))\b", re.I)
INFINITIVO = re.compile(r"^(?:[A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:ar|er|ir))(?:se|la|lo|las|los)?\b")
ERROR = re.compile(r"\b(error|falla|fallo|rechaz|sin resultados|no exist|inv[áa]lid|bloque|incierta|no deber[áa])", re.I)
MARCA_FUENTE = re.compile(r"\b[FE]\d{2}\s+(?:P|L|T|D)\d")
PRIMERA_PERSONA = re.compile(r"\b(nosotros|nuestro|nuestra|haremos|proponemos)\b", re.I)
RELLENO = re.compile(r"no (?:proporcionad|identificad|informad|consta|disponible)|por definir|pendiente de definici", re.I)
RESPONSABLE = re.compile(r"\b(cliente|sipecom|equipo|responsable|fresenius|proveedor|[áa]rea|usuario|negocio)\b", re.I)


@dataclass
class Criterio:
    id: str
    descripcion: str
    ok: bool
    detalle: str = ""


@dataclass
class Evaluacion:
    criterios: list[Criterio] = field(default_factory=list)

    @property
    def puntaje(self) -> float:
        return sum(c.ok for c in self.criterios) / len(self.criterios) if self.criterios else 0.0

    @property
    def fallas(self) -> list[Criterio]:
        return [c for c in self.criterios if not c.ok]

    def aprobado(self, umbral: float = UMBRAL) -> bool:
        return self.puntaje >= umbral

    def como_dict(self) -> dict[str, Any]:
        return {"puntaje": round(self.puntaje, 3), "umbral": UMBRAL,
                "criterios": [{"id": c.id, "descripcion": c.descripcion, "ok": c.ok, "detalle": c.detalle} for c in self.criterios]}


def _pal(texto: str) -> int:
    return len(texto.split())


def _mediana(valores: list[int]) -> float:
    return statistics.median(valores) if valores else 0


def _fuera(textos: list[str], minimo: int, maximo: int) -> list[str]:
    return [f"{_pal(t)} palabras: «{t[:60]}…»" for t in textos if not minimo <= _pal(t) <= maximo]


def evaluar(d: dict[str, Any], analisis: dict[str, dict[str, Any]] | None = None, con_codigo: bool = False,
            reglas: list[Regla] | None = None) -> Evaluacion:
    ev = Evaluacion()

    def criterio(id_: str, descripcion: str, ok: bool, detalle: str = "") -> None:
        ev.criterios.append(Criterio(id_, descripcion, bool(ok), "" if ok else detalle))

    # Capítulo 1
    j = [x for x in d["justificacion"] if x.strip()]
    criterio("justificacion", "Justificación en 2-3 párrafos de 50-110 palabras (situación actual y necesidad)",
             2 <= len(j) <= 3 and not _fuera(j, 50, 110), f"{len(j)} párrafo(s); " + "; ".join(_fuera(j, 50, 110)))
    criterio("objetivo", "Objetivo en una oración de 25-60 palabras que empieza con verbo en infinitivo",
             25 <= _pal(d["objetivo"]) <= 60 and bool(INFINITIVO.match(d["objetivo"].strip())),
             f"{_pal(d['objetivo'])} palabras; inicio «{' '.join(d['objetivo'].split()[:2])}»")
    items = d["alcance"]["items"]
    malos = [a["id"] for a in items if not INFINITIVO.match(a["descripcion"].strip()) or not 8 <= _pal(a["descripcion"]) <= 30]
    criterio("alcance", "Alcance con introducción, RF de 8-30 palabras en infinitivo y cierre de control de cambios",
             bool([x for x in d["alcance"]["introduccion"] if x.strip()]) and not malos and bool(d["alcance"]["cierre"].strip()),
             "RF a corregir: " + ", ".join(malos) if malos else "falta introducción o cierre")

    # Capítulo 2: AS-IS y transversales
    if d["tipo_proyecto"] == "existente":
        asis = [x for x in d["proceso_actual"] if x.strip()]
        criterio("as_is", "AS-IS en 3-5 párrafos de 25-80 palabras", 3 <= len(asis) <= 5 and not _fuera(asis, 25, 80),
                 f"{len(asis)} párrafo(s); " + "; ".join(_fuera(asis, 25, 80)))
    generales = d["secciones_generales"]
    criterio("transversal", "Al menos una sección transversal de integración con 2-4 párrafos",
             any(2 <= len([p for p in s["parrafos"] if p.strip()]) <= 4 for s in generales),
             f"{len(generales)} sección(es) transversal(es)")
    texto_general = " ".join(p for s in generales for p in s["parrafos"])
    criterio("tipos_resultado", "La integración distingue sin resultados, validación rechazada y falla de comunicación",
             all(re.search(p, texto_general, re.I) for p in (r"sin resultados|sin coincidencias", r"rechaz|validaci", r"falla|comunicaci|error")),
             "no se distinguen los tres tipos de resultado")

    # Requerimientos
    reqs = [r for r in d["requerimientos"] if not r["elementos"]]
    # La referencia funcional se exige cuando las fuentes traen códigos de especificación; nunca como relleno.
    con_referencias = bool(analisis) and any(a.get("referencias") for a in analisis.values())
    for r in reqs:
        rid = r["id"]
        ps = [p for p in r["parrafos"] if p.strip()]
        criterio(f"{rid}.parrafos", f"{rid}: 2-4 párrafos de 25-90 palabras (qué se adecua y datos intercambiados)",
                 2 <= len(ps) <= 4 and not _fuera(ps, 25, 90), f"{len(ps)} párrafo(s); " + "; ".join(_fuera(ps, 25, 90)))
        relleno = bool(RELLENO.search(r["referencia"]))
        if con_referencias:
            criterio(f"{rid}.referencia", f"{rid}: línea «Referencia funcional…» con código y servicio, sin texto de relleno",
                     r["referencia"].startswith("Referencia funcional") and _pal(r["referencia"]) >= 6 and not relleno,
                     f"referencia: «{r['referencia'][:80]}»")
        elif relleno:
            criterio(f"{rid}.referencia", f"{rid}: sin línea de referencia de relleno cuando las fuentes no traen códigos (dejarla vacía)",
                     False, f"referencia: «{r['referencia'][:80]}»")
        criterio(f"{rid}.flujo", f"{rid}: flujo de 4-8 pasos con actor, componente y acción", 4 <= len(r["flujo"]) <= 8
                 and all(p["actor"].strip() and p["componente"].strip() and _pal(p["accion"]) >= 5 for p in r["flujo"]),
                 f"{len(r['flujo'])} paso(s)")
        cs = r["criterios_aceptacion"]
        largos = [_pal(c) for c in cs]
        normativos = sum(bool(NORMATIVO.search(c)) for c in cs)
        criterio(f"{rid}.criterios", f"{rid}: 4-9 criterios de 15-45 palabras (mediana ≥ 18) en voz normativa e incluyendo un caso de error",
                 4 <= len(cs) <= 9 and _mediana(largos) >= 18 and min(largos or [0]) >= 12 and normativos >= 0.7 * len(cs)
                 and any(ERROR.search(c) for c in cs),
                 f"{len(cs)} criterios, mediana {_mediana(largos):.0f} palabras, {normativos} con «deberá», "
                 f"{'con' if any(ERROR.search(c) for c in cs) else 'sin'} caso de error")
    for r in [x for x in d["requerimientos"] if x["elementos"]]:
        cortos = [e["titulo"] for e in r["elementos"] if _pal(e["detalle"]) < 15]
        criterio(f"{r['id']}.escenarios", f"{r['id']}: cada escenario con detalle de al menos 15 palabras y 3+ criterios",
                 not cortos and len(r["criterios_aceptacion"]) >= 3, "escenarios breves: " + ", ".join(cortos[:5]))

    # Componentes, prerrequisitos, restricciones, definiciones, anexos
    if d["tipo_proyecto"] == "existente":
        comp = d["componentes"]["items"]
        sin_ubicacion = [c["componente"] for c in comp if con_codigo and not c["ubicacion"].strip()]
        breves = [c["componente"] for c in comp if _pal(c["adecuacion"]) < 8]
        criterio("componentes", "Adecuaciones por componente (con repositorio si se revisó el código) y adecuación de 8+ palabras",
                 len(comp) >= (4 if con_codigo else 2) and not sin_ubicacion and not breves,
                 f"{len(comp)} componente(s); sin repositorio: {', '.join(sin_ubicacion[:4])}; adecuación breve: {', '.join(breves[:4])}")
    pre = d["prerrequisitos"]["items"]
    sin_resp = [p[:40] for p in pre if not RESPONSABLE.search(p)]
    criterio("prerrequisitos", "Hasta 14 prerrequisitos reales de 12-50 palabras, cada uno con responsable",
             len(pre) <= 14 and not _fuera(pre, 12, 50) and not sin_resp,
             f"{len(pre)} prerrequisito(s); sin responsable: {len(sin_resp)}")
    rest = d["restricciones"]
    criterio("restricciones", "8-12 restricciones de 12-50 palabras", 8 <= len(rest) <= 12 and not _fuera(rest, 12, 50),
             f"{len(rest)} restricción(es); " + "; ".join(_fuera(rest, 12, 50)[:3]))
    defs = d["definiciones"]
    if defs:
        largas = [x["id"] for x in defs if not 20 <= _pal(x["descripcion"]) <= 90]
        una_fuente = [x["id"] for x in defs if len({e.split()[0] for e in x["evidencias"] if e.strip()}) < 1]
        titulos = [x["id"] for x in defs if _pal(x["titulo"]) > 7]
        criterio("definiciones", "Definiciones D-xx de 20-90 palabras, título breve y evidencias",
                 not largas and not una_fuente and not titulos,
                 f"extensión fuera de rango: {', '.join(largas[:6])}; sin evidencia: {', '.join(una_fuente[:6])}; títulos largos: {', '.join(titulos[:4])}")
    preguntas = d.get("preguntas_cliente", [])
    if not d.get("cambios"):  # al adaptar, las preguntas respondidas se eliminan: no se exige un mínimo
        cubiertas = {x for p in preguntas for x in p["relacion"]}
        sin_pregunta = [x["id"] for x in defs if x["id"] not in cubiertas]
        mal_formadas = [p["id"] for p in preguntas if not p["pregunta"].strip().endswith("?") or not 10 <= _pal(p["contexto"]) <= 60
                        or _pal(p["tema"]) > 4]
        criterio("preguntas", "Preguntas para el cliente: al menos una por D-xx (mínimo 8), con tema breve, contexto de 10-60 palabras y pregunta directa",
                 len(preguntas) >= max(8, len(defs)) and not sin_pregunta and not mal_formadas,
                 f"{len(preguntas)} pregunta(s); D-xx sin pregunta: {', '.join(sin_pregunta[:6])}; a corregir: {', '.join(mal_formadas[:6])}")

    # Estilo global
    textos = (d["justificacion"] + [d["objetivo"]] + d["proceso_actual"] + [p for s in generales for p in s["parrafos"]]
              + [p for r in d["requerimientos"] for p in r["parrafos"] + r["criterios_aceptacion"] + [e["detalle"] for e in r["elementos"]]]
              + pre + rest + [x["descripcion"] for x in defs])
    todo = " ".join(textos)
    criterio("sin_marcas", "Sin marcas de fuente (F01 P12, L8…) dentro de los textos", not MARCA_FUENTE.search(todo),
             "ejemplo: " + (MARCA_FUENTE.search(todo).group(0) if MARCA_FUENTE.search(todo) else ""))
    criterio("sin_formato", "Sin markdown, viñetas embebidas ni primera persona",
             not re.search(r"\*\*|^#|\n[-*] ", todo, re.M) and not PRIMERA_PERSONA.search(todo), "formato o primera persona en el texto")
    total_criterios = sum(len(r["criterios_aceptacion"]) for r in d["requerimientos"])
    criterio("voz_normativa", "Voz normativa: al menos un «deberá» por criterio de aceptación en el documento",
             len(NORMATIVO.findall(todo)) >= total_criterios, f"{len(NORMATIVO.findall(todo))} expresiones normativas para {total_criterios} criterios")

    # Reglas del equipo con verificación automática: entran en la corrección editorial como cualquier criterio.
    for r in reglas or []:
        resultado = verificar(d, r)
        if resultado is not None:
            accion = "Evitar" if r.tipo == "evitar" else "Exigir"
            criterio(f"regla.{r.etiqueta}", f"Regla del equipo {r.etiqueta} ({accion}, {SECCIONES[r.seccion].lower()}): {r.texto}",
                     resultado[0], resultado[1])
    return ev


def instrucciones_correccion(ev: Evaluacion) -> str:
    return "\n".join(f"- [{c.id}] {c.descripcion}. Situación actual: {c.detalle}" for c in ev.fallas)
