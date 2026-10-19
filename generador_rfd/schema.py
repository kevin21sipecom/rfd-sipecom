"""Esquemas de intercambio con el modelo: análisis por fuente y RFD (v2) para el renderizador Word."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


STRING = {"type": "string"}
STRINGS = arr(STRING)
INTEGER_OR_NULL = {"anyOf": [{"type": "integer"}, {"type": "null"}]}

# Análisis de una fuente (fase 1). Una llamada por documento.
SCHEMA_ANALISIS: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **obj(
        {
            "tipo": {"type": "string", "enum": ["especificacion_interfaz", "especificacion_funcional", "presentacion", "acta_reunion", "otro"]},
            "titulo": STRING,
            "resumen": STRING,
            "referencias": STRINGS,
            "servicios": STRINGS,
            "direccion": STRING,
            "sistemas": STRINGS,
            "paises": STRINGS,
            "datos_solicitud": STRINGS,
            "datos_respuesta": STRINGS,
            "reglas": STRINGS,
            "validaciones": STRINGS,
            "errores_y_mensajes": STRINGS,
            "dependencias": STRINGS,
            "escenarios": arr(obj({"nombre": STRING, "descripcion": STRING})),
            "dudas_y_contradicciones": STRINGS,
            "terminos_codigo": STRINGS,
            "evidencias": STRINGS,
        }
    ),
}

PARRAFOS = arr(STRING)

# Especificación detallada de una opción, por portal o perfil: el nivel de un RFD con pantallas
# (definiciones generales, ventanas con sus secciones y campos, reglas de negocio) e integraciones.
VISTA = obj(
    {
        "portal": STRING,
        "definiciones_generales": STRINGS,
        "ventanas": arr(
            obj(
                {
                    "nombre": STRING,
                    "descripcion": STRING,
                    "secciones": arr(
                        obj(
                            {
                                "nombre": STRING,
                                "descripcion": STRING,
                                "campos": arr(obj({"nombre": STRING, "tipo": STRING, "descripcion": STRING})),
                            }
                        )
                    ),
                }
            )
        ),
        "reglas_negocio": STRINGS,
    }
)
ESPECIFICACION = {"vistas": arr(VISTA), "integraciones": arr(obj({"servicio": STRING, "descripcion": STRING}))}

# Detalle de un requerimiento (una llamada por opción). Las secciones reemplazadas son resúmenes superados.
SCHEMA_DETALLE: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **obj({**ESPECIFICACION, "secciones_reemplazadas": STRINGS}),
}

SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **obj(
        {
            "titulo": STRING,
            "cliente": STRING,
            "codigo": STRING,
            "fecha": STRING,
            "tipo_proyecto": {"type": "string", "enum": ["nuevo", "existente"]},
            "justificacion": PARRAFOS,
            "objetivo": STRING,
            "alcance": obj(
                {
                    "introduccion": PARRAFOS,
                    "items": arr(obj({"id": STRING, "descripcion": STRING})),
                    "cierre": STRING,
                }
            ),
            "proceso_actual": PARRAFOS,
            "secciones_generales": arr(obj({"titulo": STRING, "parrafos": PARRAFOS})),
            "requerimientos": arr(
                obj(
                    {
                        "id": STRING,
                        "nombre": STRING,
                        "parrafos": PARRAFOS,
                        "referencia": STRING,
                        "elementos": arr(obj({"titulo": STRING, "detalle": STRING})),
                        "flujo": arr(
                            obj(
                                {
                                    "numero": {"type": "integer"},
                                    "actor": STRING,
                                    "componente": STRING,
                                    "accion": STRING,
                                }
                            )
                        ),
                        "criterios_aceptacion": STRINGS,
                        "evidencias": STRINGS,
                        **ESPECIFICACION,
                    }
                )
            ),
            "componentes": obj(
                {
                    "id": STRING,
                    "titulo": STRING,
                    "introduccion": STRING,
                    "items": arr(obj({"componente": STRING, "ubicacion": STRING, "adecuacion": STRING})),
                }
            ),
            "prerrequisitos": obj({"introduccion": STRING, "items": STRINGS}),
            "definiciones": arr(obj({"id": STRING, "titulo": STRING, "descripcion": STRING, "evidencias": STRINGS})),
            "restricciones": STRINGS,
            "entregables": arr(obj({"fase": STRING, "entregable": STRING})),
            "esfuerzo": obj(
                {
                    "introduccion": STRING,
                    "actividades": arr(obj({"actividad": STRING, "horas": INTEGER_OR_NULL})),
                    "total_horas": INTEGER_OR_NULL,
                    "duracion": STRING,
                    "notas": STRINGS,
                }
            ),
            "responsables": obj(
                {
                    "autor": STRING,
                    "revisor": STRING,
                    "aprobador_sipecom": STRING,
                    "aprobador_cliente": STRING,
                }
            ),
            "anexos": arr(obj({"id": STRING, "nombre": STRING, "uso": STRING})),
            "preguntas_cliente": arr(obj({"id": STRING, "tema": STRING, "contexto": STRING, "pregunta": STRING, "relacion": STRINGS})),
            "cambios": arr(obj({"pregunta": STRING, "seccion": STRING, "cambio": STRING})),
            "supuestos": STRINGS,
            "pendientes": arr(obj({"pregunta": STRING, "motivo": STRING})),
        }
    ),
}

# Metadatos de control que agrega el programa (no el modelo): versión e historial de revisiones.
CONTROL = ("version", "historial")


@dataclass(frozen=True)
class Hallazgo:
    codigo: str
    mensaje: str


def validar_contra(datos: dict[str, Any], esquema: dict[str, Any], nombre: str = "RFD") -> None:
    """Validación estricta del subconjunto JSON Schema usado por los contratos."""
    errores: list[str] = []

    def coincide(valor: Any, sub: dict[str, Any]) -> bool:
        tipo = sub.get("type")
        return {
            "object": lambda: isinstance(valor, dict),
            "array": lambda: isinstance(valor, list),
            "string": lambda: isinstance(valor, str),
            "integer": lambda: isinstance(valor, int) and not isinstance(valor, bool),
            "null": lambda: valor is None,
        }.get(tipo, lambda: True)()

    def revisar(valor: Any, sub: dict[str, Any], ruta: str) -> None:
        if "anyOf" in sub:
            if not any(coincide(valor, v) for v in sub["anyOf"]):
                errores.append(f"{ruta}: tipo no admitido")
            return
        if not coincide(valor, sub):
            errores.append(f"{ruta}: tipo esperado {sub.get('type')}")
            return
        if "enum" in sub and valor not in sub["enum"]:
            errores.append(f"{ruta}: valor no admitido {valor!r}")
        if sub.get("type") == "object":
            propiedades = sub.get("properties", {})
            for campo in sub.get("required", []):
                if campo not in valor:
                    errores.append(f"{ruta}.{campo}: falta campo")
            if sub.get("additionalProperties") is False:
                for campo in valor.keys() - propiedades.keys():
                    errores.append(f"{ruta}.{campo}: campo no permitido")
            for campo, s in propiedades.items():
                if campo in valor:
                    revisar(valor[campo], s, f"{ruta}.{campo}")
        if sub.get("type") == "array":
            for i, item in enumerate(valor):
                revisar(item, sub["items"], f"{ruta}[{i}]")

    revisar(datos, esquema, "raíz")
    if errores:
        raise ValueError(f"JSON de {nombre} inválido: " + "; ".join(errores[:8]))


def validar_estructura(datos: dict[str, Any]) -> None:
    validar_contra({k: v for k, v in datos.items() if k not in CONTROL}, SCHEMA, "RFD")
    if not isinstance(datos.get("version", ""), str) or not isinstance(datos.get("historial", []), list):
        raise ValueError("JSON de RFD inválido: version o historial con tipo incorrecto")


def normalizar(datos: dict[str, Any]) -> dict[str, Any]:
    """Completa campos agregados en versiones posteriores para que un RFD anterior siga siendo base válida."""
    datos.setdefault("preguntas_cliente", [])
    datos.setdefault("cambios", [])
    datos.setdefault("version", "0.1")
    datos.setdefault("historial", [])
    for r in datos.get("requerimientos", []):
        r.setdefault("vistas", [])
        r.setdefault("integraciones", [])
    return datos


VAGOS = ["funciona correctamente", "adecuadamente", "intuitivo", "rápido", "amigable", "óptimo"]


def auditar_contenido(d: dict[str, Any]) -> list[Hallazgo]:
    h: list[Hallazgo] = []

    def vacio(valor: Any) -> bool:
        return not "".join(valor).strip() if isinstance(valor, list) else not str(valor).strip()

    for campo in ["titulo", "cliente", "codigo", "fecha", "justificacion", "objetivo"]:
        if vacio(d[campo]):
            h.append(Hallazgo("dato_faltante", f"Falta {campo}."))
    if d["tipo_proyecto"] == "existente" and vacio(d["proceso_actual"]):
        h.append(Hallazgo("as_is_faltante", "El proyecto existente necesita descripción del proceso actual (AS-IS)."))
    if not d["alcance"]["items"]:
        h.append(Hallazgo("alcance_faltante", "El alcance no contiene requerimientos."))
    if not d["requerimientos"]:
        h.append(Hallazgo("requerimientos_faltantes", "No hay requerimientos funcionales."))
    ids = [r["id"] for r in d["requerimientos"]]
    if len(ids) != len(set(ids)):
        h.append(Hallazgo("id_duplicado", "Hay identificadores de requerimiento duplicados."))
    ids_alcance = {a["id"] for a in d["alcance"]["items"]}
    documentados = set(ids) | ({d["componentes"]["id"]} if d["componentes"]["items"] else set())
    for falta_rf in sorted(ids_alcance - documentados):
        h.append(Hallazgo("alcance_sin_detalle", f"{falta_rf} figura en el alcance pero no tiene sección de detalle."))
    for r in d["requerimientos"]:
        ref = r["id"] or "sin ID"
        if ref not in ids_alcance:
            h.append(Hallazgo("fuera_de_alcance", f"{ref} no figura en la tabla de alcance."))
        if vacio(r["parrafos"]):
            h.append(Hallazgo("descripcion_faltante", f"{ref} no tiene descripción."))
        if not r["elementos"] and len(r["flujo"]) < 2:
            h.append(Hallazgo("flujo_incompleto", f"{ref} necesita al menos dos pasos de flujo."))
        if len(r["criterios_aceptacion"]) < 2:
            h.append(Hallazgo("criterios_incompletos", f"{ref} necesita al menos dos criterios verificables."))
        if not r["evidencias"]:
            h.append(Hallazgo("sin_trazabilidad", f"{ref} no tiene referencia a una fuente."))
        for c in r["criterios_aceptacion"]:
            if any(v in c.lower() for v in VAGOS):
                h.append(Hallazgo("criterio_vago", f"{ref} contiene un criterio no verificable: {c}"))
        for v in r["vistas"]:
            if not v["ventanas"] or not v["reglas_negocio"]:
                h.append(Hallazgo("especificacion_incompleta",
                                  f"{ref} ({v['portal'] or 'sin portal'}) necesita ventanas y reglas de negocio en su especificación."))
    if d["tipo_proyecto"] == "existente" and not d["componentes"]["items"]:
        h.append(Hallazgo("componentes_faltantes", "No se identificaron componentes existentes a adecuar."))
    if not d["entregables"]:
        h.append(Hallazgo("entregables_faltantes", "No hay entregables definidos."))
    e = d["esfuerzo"]
    horas = [x["horas"] for x in e["actividades"]]
    if e["total_horas"] is None or not horas or any(x is None for x in horas):
        h.append(Hallazgo("esfuerzo_pendiente", "Falta una estimación de esfuerzo aprobada."))
    elif sum(horas) != e["total_horas"]:
        h.append(Hallazgo("esfuerzo_inconsistente", "El total de horas no coincide con el desglose."))
    if d["definiciones"]:
        h.append(Hallazgo("definiciones", f"Hay {len(d['definiciones'])} definición(es) por resolver antes de construir."))
    if d.get("preguntas_cliente"):
        h.append(Hallazgo("preguntas_cliente", f"Hay {len(d['preguntas_cliente'])} pregunta(s) para el cliente sin responder."))
    if d["supuestos"]:
        h.append(Hallazgo("supuestos", "El documento contiene supuestos pendientes de validación."))
    if d["pendientes"]:
        h.append(Hallazgo("pendientes", "El documento tiene preguntas abiertas."))
    return h


MARCADOR_PLANTILLA = re.compile(r"\[(?:Nombre|Cargo|Versión|Fecha|Situación|Resultado|Proceso|Comportamiento|Criterio|Prerrequisito|Límite|Entregable|Horas|Interfaces|Descripción|total|duración)[^\]]*\]")


def auditar_texto_final(texto: str, terminos_ajenos: list[str]) -> list[Hallazgo]:
    """Revisión del Word ya armado: instrucciones de llenado y contenido heredado de referencias de estilo."""
    h: list[Hallazgo] = []
    restos = sorted(set(MARCADOR_PLANTILLA.findall(texto)))
    if restos:
        h.append(Hallazgo("instrucciones_plantilla", "Quedan instrucciones de la plantilla: " + ", ".join(restos[:6])))
    heredados = sorted({t for t in terminos_ajenos if re.search(rf"\b{re.escape(t)}\b", texto)})
    if heredados:
        h.append(Hallazgo("referencia_heredada", "Aparecen términos de la referencia de estilo: " + ", ".join(heredados[:8])))
    return h
