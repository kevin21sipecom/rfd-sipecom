"""Reglas del equipo: instrucciones que se inyectan al modelo y, si traen patrón, se verifican en el RFD.

Una regla «evitar» dice lo que el modelo no debe hacer (p. ej. «No usar "etc."»); una regla «exigir»,
lo que debe aparecer (p. ej. «Cada requerimiento indica el comportamiento ante timeout»). Se guardan en
SQLite (tabla `reglas`), pueden aplicar a todos los clientes o a uno, y a todo el documento o a una sección.

Verificación automática (opcional), con el campo `patron`:
- Términos separados por «|», sin distinguir mayúsculas: `etc.|entre otros|TBD`.
- Expresión regular con el prefijo «re:»: `re:\\b\\d+ horas\\b`.
«evitar» falla si algún término aparece en la sección. «exigir» falla si no aparece; en las secciones
de requerimientos, criterios o flujo se exige en cada requerimiento.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

TIPOS = ("evitar", "exigir")
SECCIONES: dict[str, str] = {
    "todo": "Todo el documento",
    "justificacion": "Justificación",
    "objetivo": "Objetivo",
    "alcance": "Alcance",
    "proceso_actual": "Proceso actual (AS-IS)",
    "requerimientos": "Requerimientos",
    "criterios": "Criterios de aceptación",
    "flujo": "Flujos",
    "componentes": "Componentes",
    "prerrequisitos": "Prerrequisitos",
    "definiciones": "Definiciones",
    "restricciones": "Restricciones",
    "entregables": "Entregables",
    "esfuerzo": "Esfuerzo",
    "preguntas": "Preguntas para el cliente",
}
POR_REQUERIMIENTO = {"requerimientos", "criterios", "flujo"}


@dataclass
class Regla:
    texto: str
    tipo: str = "evitar"
    seccion: str = "todo"
    patron: str = ""
    cliente: str = ""
    activa: bool = True
    id: int | None = None

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def etiqueta(self) -> str:
        return f"R{self.id}" if self.id is not None else "R"


def validar_regla(r: Regla) -> Regla:
    r.texto = " ".join(r.texto.split())
    r.patron = r.patron.strip()
    r.cliente = r.cliente.strip()
    if len(r.texto) < 5:
        raise ValueError("Escriba la regla con al menos una frase corta.")
    if r.tipo not in TIPOS:
        raise ValueError("El tipo de regla debe ser «evitar» o «exigir».")
    if r.seccion not in SECCIONES:
        raise ValueError(f"Sección no válida: {r.seccion}.")
    compilar(r.patron)
    return r


def compilar(patron: str) -> re.Pattern[str] | None:
    """`a|b` → términos literales; `re:…` → expresión regular. Vacío → sin verificación automática."""
    patron = patron.strip()
    if not patron:
        return None
    try:
        if patron.lower().startswith("re:"):
            return re.compile(patron[3:].strip(), re.I)
        terminos = [t.strip() for t in patron.split("|") if t.strip()]
        partes = [(r"(?<!\w)" if t[0].isalnum() else "") + re.escape(t) + (r"(?!\w)" if t[-1].isalnum() else "") for t in terminos]
        return re.compile("|".join(partes), re.I) if partes else None
    except re.error as e:
        raise ValueError(f"La verificación «{patron}» no es una expresión válida: {e}") from e


# ---------------------------------------------------------------- prompt

def bloque_prompt(reglas: list[Regla]) -> str:
    activas = [r for r in reglas if r.activa]
    if not activas:
        return ""
    lineas = [
        "REGLAS DEL EQUIPO (obligatorias; prevalecen sobre la guía de redacción y las metas de extensión, "
        "nunca sobre las reglas de integridad)",
    ]
    for r in activas:
        verbo = "NO HACER" if r.tipo == "evitar" else "HACER SIEMPRE"
        ambito = SECCIONES[r.seccion] + (f" · sólo para {r.cliente}" if r.cliente else "")
        lineas.append(f"- [{r.etiqueta}] {verbo} ({ambito}): {r.texto}")
    return "\n".join(lineas)


# ---------------------------------------------------------------- verificación

Texto = tuple[str, str]  # (ubicación legible, texto)


def _req(d: dict[str, Any]) -> list[tuple[str, list[Texto], list[Texto], list[Texto]]]:
    """Por requerimiento: (id, textos completos, criterios, flujo)."""
    salida = []
    for r in d.get("requerimientos", []):
        rid = r["id"]
        criterios = [(f"{rid} criterio {i}", c) for i, c in enumerate(r.get("criterios_aceptacion", []), 1)]
        flujo = [(f"{rid} paso {p.get('numero', i)}", p.get("accion", "")) for i, p in enumerate(r.get("flujo", []), 1)]
        textos = ([(f"{rid} {r.get('nombre', '')}", r.get("nombre", ""))]
                  + [(f"{rid} párrafo {i}", p) for i, p in enumerate(r.get("parrafos", []), 1)]
                  + [(f"{rid} referencia", r.get("referencia", ""))] + flujo + criterios
                  + [(f"{rid} {e.get('titulo', '')}", e.get("detalle", "")) for e in r.get("elementos", [])])
        salida.append((rid, textos, criterios, flujo))
    return salida


def textos_de(d: dict[str, Any], seccion: str) -> list[Texto]:
    alcance = d.get("alcance", {})
    comp = d.get("componentes", {})
    esf = d.get("esfuerzo", {})
    reqs = _req(d)
    por_seccion: dict[str, list[Texto]] = {
        "justificacion": [(f"Justificación párrafo {i}", p) for i, p in enumerate(d.get("justificacion", []), 1)],
        "objetivo": [("Objetivo", d.get("objetivo", ""))],
        "alcance": [("Alcance introducción", p) for p in alcance.get("introduccion", [])]
                   + [(f"Alcance {a['id']}", a["descripcion"]) for a in alcance.get("items", [])]
                   + [("Alcance cierre", alcance.get("cierre", ""))],
        "proceso_actual": [(f"AS-IS párrafo {i}", p) for i, p in enumerate(d.get("proceso_actual", []), 1)],
        "requerimientos": [(s.get("titulo", "Sección general"), p) for s in d.get("secciones_generales", []) for p in s.get("parrafos", [])]
                          + [t for _, textos, _, _ in reqs for t in textos],
        "criterios": [t for _, _, c, _ in reqs for t in c],
        "flujo": [t for _, _, _, f in reqs for t in f],
        "componentes": [(f"Componente {c['componente']}", f"{c['componente']} {c['adecuacion']}") for c in comp.get("items", [])],
        "prerrequisitos": [(f"Prerrequisito {i}", p) for i, p in enumerate(d.get("prerrequisitos", {}).get("items", []), 1)],
        "definiciones": [(x["id"], f"{x['titulo']}. {x['descripcion']}") for x in d.get("definiciones", [])],
        "restricciones": [(f"Restricción {i}", p) for i, p in enumerate(d.get("restricciones", []), 1)],
        "entregables": [(f"Entregable {e.get('fase', '')}", e.get("entregable", "")) for e in d.get("entregables", [])],
        "esfuerzo": [("Esfuerzo", esf.get("introduccion", ""))] + [(f"Esfuerzo nota {i}", n) for i, n in enumerate(esf.get("notas", []), 1)]
                    + [(f"Actividad {a.get('actividad', '')}", f"{a.get('actividad', '')} {a.get('horas') or ''}") for a in esf.get("actividades", [])]
                    + [("Duración", esf.get("duracion", "") or "")],
        "preguntas": [(p["id"], f"{p['contexto']} {p['pregunta']}") for p in d.get("preguntas_cliente", [])],
    }
    if seccion == "todo":
        return [("Título", d.get("titulo", ""))] + [t for k, v in por_seccion.items() if k not in ("criterios", "flujo") for t in v]
    return por_seccion.get(seccion, [])


def verificar(d: dict[str, Any], regla: Regla) -> tuple[bool, str] | None:
    """(cumple, detalle) de una regla con patrón; None si la regla es sólo una instrucción."""
    patron = compilar(regla.patron)
    if patron is None or not regla.activa:
        return None
    if regla.tipo == "evitar":
        hallados = [(u, m.group(0), t) for u, t in textos_de(d, regla.seccion) if t and (m := patron.search(t))]
        if not hallados:
            return True, ""
        ejemplos = "; ".join(f"{u}: «{_contexto(t, h)}»" for u, h, t in hallados[:3])
        return False, f"aparece {len(hallados)} vez/veces — {ejemplos}"
    if regla.seccion in POR_REQUERIMIENTO:
        indice = {"requerimientos": 1, "criterios": 2, "flujo": 3}[regla.seccion]
        faltan = [rid for rid, *partes in _req(d) if partes[indice - 1] and not any(patron.search(t) for _, t in partes[indice - 1])]
        return (not faltan, "falta en " + ", ".join(faltan) if faltan else "")
    textos = textos_de(d, regla.seccion)
    return (True, "") if any(patron.search(t) for _, t in textos) else (False, f"no aparece en {SECCIONES[regla.seccion].lower()}")


def _contexto(texto: str, hallado: str, ancho: int = 50) -> str:
    i = texto.lower().find(hallado.lower())
    i = max(0, i)
    inicio, fin = max(0, i - ancho), min(len(texto), i + len(hallado) + ancho)
    return ("…" if inicio else "") + texto[inicio:fin].strip() + ("…" if fin < len(texto) else "")


def incumplidas(d: dict[str, Any], reglas: list[Regla]) -> list[tuple[Regla, str]]:
    salida = []
    for r in reglas:
        resultado = verificar(d, r)
        if resultado is not None and not resultado[0]:
            salida.append((r, resultado[1]))
    return salida
