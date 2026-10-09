"""Reglas predeterminadas del equipo: «Reglas y correcciones para el generador de RFD» v1.0 (9/10/2026).

Seis observaciones sobre contenido interno que el generador trasladaba al RFD del cliente, con treinta
reglas (REG-001 a REG-030). Se cargan en la tabla `reglas` la primera vez que se abre el historial y
pueden desactivarse o ajustarse desde la pestaña Reglas, pero no eliminarse.

Los patrones sólo localizan frases típicas de la narrativa del agente: al fallar, el mismo modelo corrige
con el contexto completo (las palabras «tokens», «revisión», «fuente» o un nombre propio no bastan para
eliminar contenido). Se evitan patrones sobre términos que pueden ser legítimos del sistema del cliente.
"""

from __future__ import annotations

OBSERVACIONES: dict[str, str] = {
    "001": "Narrativas internas y autoconfirmaciones",
    "002": "Justificaciones por información no disponible",
    "003": "Prerrequisitos y asignaciones internas",
    "004": "Nombres propios y datos del operador",
    "005": "Decisiones pendientes y coordinación interna",
    "006": "Anexos de trabajo y trazabilidad interna",
}

CONDICIONES = """CONDICIONES DE APLICACIÓN DE LAS REGLAS PREDETERMINADAS
- El RFD es para el cliente: explica la necesidad, las funcionalidades y el alcance de la solución, sin trasladar conversaciones, instrucciones ni registros del proceso interno de elaboración.
- Antes de redactar, clasifica la información por su función: contenido del proyecto, instrucciones internas y decisiones pendientes. Usa sólo el contenido pertinente al entregable.
- Eliminar una explicación del agente no autoriza a inventar funcionalidades, convertir hipótesis en compromisos ni ocultar una indefinición que afecte al alcance. Un dato indispensable pendiente va a «pendientes» (registro interno); si debe figurar en el RFD, se expresa como una definición concreta pendiente, sin justificar las limitaciones del análisis.
- Evalúa los términos por su significado: un token de autenticación puede pertenecer al sistema del cliente; el consumo de tokens de la IA pertenece al proceso de generación y queda fuera. Las palabras «tokens», «revisión», «fuente» o un nombre propio no son motivo suficiente para eliminar contenido."""

# (código, observación, tipo, sección, texto, patrón de verificación)
REGLAS: list[tuple[str, str, str, str, str, str]] = [
    # Observación 001 — capítulo 1
    ("REG-001", "001", "evitar", "todo", "Excluir referencias al proceso interno de generación con IA, incluidos consumo de tokens, instrucciones y herramientas del agente.",
     r"re:consumo de tokens|tokens de (?:la )?IA"),
    ("REG-002", "001", "evitar", "todo", "Eliminar autoconfirmaciones y explicaciones del agente sobre lo que hará, verificará o podrá realizar.", ""),
    ("REG-003", "001", "evitar", "todo", "Excluir condiciones de revisión humana o aprobación propias del agente. Conservar solo aprobaciones del proyecto expresamente definidas.",
     r"re:revisi[oó]n humana|no autoriza(?:n)? (?:a )?iniciar|autoriza\w* iniciar (?:directamente )?la implementaci[oó]n"),
    ("REG-004", "001", "exigir", "todo", "Redactar desde la necesidad del cliente, con objetivos, funcionalidades, restricciones y alcance de la solución.", ""),
    ("REG-005", "001", "evitar", "todo", "Separar el contexto operativo del agente de los hechos y requisitos que corresponden al entregable.", ""),
    # Observación 002 — capítulo 2
    ("REG-006", "002", "evitar", "todo", "Excluir justificaciones sobre documentación, archivos o código que no recibió el agente.",
     r"re:no se (?:suministr|proporcion|recibi|entreg|aport)\w*|documentaci[oó]n recibida|inventario (?:suministrado|disponible|parcial)|los fragmentos (?:no|revisados)|c[oó]digo (?:recibido|suministrado)"),
    ("REG-007", "002", "evitar", "todo", "Evitar expresiones como «no se suministró», «la fuente no demuestra» o «no se dispone» cuando explican límites del análisis del agente.",
     r"re:la fuente no (?:demuestra|autoriza|permite|indica|precisa)|no se dispone de|no se demuestra|no permite verificar|no (?:es|fue) posible verificar"),
    ("REG-008", "002", "evitar", "requerimientos", "No convertir automáticamente una limitación del análisis en un párrafo o requerimiento del RFD.", ""),
    ("REG-009", "002", "exigir", "requerimientos", "Formular los requerimientos como capacidades y condiciones del sistema, con respaldo en el alcance definido.", ""),
    ("REG-010", "002", "exigir", "todo", "Registrar internamente los datos faltantes. Si una indefinición afecta al alcance, expresarla de manera objetiva sin inventar su resolución.", ""),
    # Observación 003 — capítulo 3, prerrequisitos
    ("REG-011", "003", "evitar", "prerrequisitos", "No incorporar solicitudes de código, repositorios o documentación como prerrequisitos por el solo hecho de que el agente las necesite.",
     r"re:(?:facilitar|proporcionar|entregar) (?:el )?c[oó]digo|versi[oó]n autoritativa|ramas y versiones"),
    ("REG-012", "003", "evitar", "prerrequisitos", "No asignar tareas ni responsabilidades a personas sin una definición expresa del proyecto.", ""),
    ("REG-013", "003", "evitar", "todo", "Excluir relaciones personales y nombres provenientes del contexto interno cuando no sean necesarios para el alcance.", ""),
    ("REG-014", "003", "evitar", "prerrequisitos", "No transformar actividades internas de inspección o levantamiento en obligaciones del cliente.", ""),
    ("REG-015", "003", "exigir", "prerrequisitos", "Incluir prerrequisitos solo cuando sean condiciones reales del proyecto y estén expresamente definidas.", ""),
    # Observación 004 — nombres y datos del operador
    ("REG-016", "004", "evitar", "todo", "Evitar menciones innecesarias de operadores, analistas o personas que interactúan con el generador.", ""),
    ("REG-017", "004", "evitar", "todo", "No asumir que quien solicita el documento es el cliente, beneficiario o representante contractual.", ""),
    ("REG-018", "004", "exigir", "todo", "Usar denominaciones institucionales y roles funcionales cuando sean pertinentes y estén definidos.", ""),
    ("REG-019", "004", "evitar", "todo", "No trasladar al RFD datos personales obtenidos de la conversación que no formen parte de la información del proyecto.", ""),
    ("REG-020", "004", "exigir", "todo", "Incluir nombres de personas solo cuando su participación esté confirmada y exista una necesidad documental concreta.", ""),
    # Observación 005 — definiciones y coordinación interna
    ("REG-021", "005", "evitar", "todo", "Excluir conversaciones internas entre colaboradores del contenido destinado al cliente.", ""),
    ("REG-022", "005", "evitar", "preguntas", "No incluir preguntas dirigidas a responsables técnicos ni consultas que deban resolverse internamente.", ""),
    ("REG-023", "005", "evitar", "todo", "No presentar alternativas arquitectónicas o reutilización de componentes como requisitos aprobados sin confirmación.", ""),
    ("REG-024", "005", "evitar", "todo", "Excluir referencias a operadores, transcripciones, destinatarios y fechas de elaboración ajenas al alcance acordado.",
     r"re:(?:la|seg[uú]n la) transcripci[oó]n|fecha de elaboraci[oó]n|etapa (?:actualmente )?solicitada|elaboraci[oó]n del RFD"),
    ("REG-025", "005", "exigir", "definiciones", "Mantener las decisiones técnicas pendientes en el registro interno; incorporar al RFD solo su resultado cuando corresponda y esté definido.", ""),
    # Observación 006 — capítulo 8, anexos
    ("REG-026", "006", "evitar", "anexos", "No incorporar automáticamente archivos de trabajo, transcripciones, inventarios o repositorios internos como anexos del cliente.",
     r"re:\.(?:pdf|docx?|pptx?|txt|md|xlsx?)\b|transcripci[oó]n|inventario|repositorio"),
    ("REG-027", "006", "evitar", "todo", "Excluir referencias a herramientas de análisis y generación, como CodeGraph, cuando solo expliquen la elaboración del documento.",
     "CodeGraph|Repomix"),
    ("REG-028", "006", "evitar", "anexos", "Conservar internamente la relación entre fuentes y requerimientos, sin publicarla por defecto como parte del RFD.",
     r"re:base de RF-|sustento (?:AS-IS|de RF)"),
    ("REG-029", "006", "exigir", "anexos", "Incluir anexos únicamente cuando sean pertinentes al alcance y estén solicitados o definidos para el entregable.", ""),
    ("REG-030", "006", "evitar", "anexos", "Retirar un capítulo de anexos si solo contiene material interno; actualizar el índice, la numeración y las referencias afectadas.", ""),
]
