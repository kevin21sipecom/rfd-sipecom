# Plan de implementación

## Fase 1: archivos locales y revisión humana

1. Ingesta de una o varias transcripciones `.txt`/`.docx` y documentos de contexto del proyecto.
2. Extracción ordenada de texto y etiquetas de procedencia por archivo, párrafo, tabla o línea.
3. Síntesis estructurada mediante `codex exec --oss` con Ollama o LM Studio; la salida debe cumplir un esquema JSON.
4. Validación de completitud, coherencia, trazabilidad y preparación para público.
5. Producción del RFD Word a partir del DOCX SIPECOM aprobado y emisión de un informe de revisión.
6. Revisión y aprobación por analista funcional antes de circulación externa.

## Fase 2: contexto Azure DevOps

Agregar un adaptador para el MCP propio de Azure DevOps: búsqueda de proyecto, épicas, historias, bugs, decisiones y adjuntos; normalización en el mismo esquema de fuentes; trazabilidad bidireccional RFD–work item. Definir antes permisos de lectura, política de datos, proyectos habilitados y cómo se resuelven conflictos entre reunión y backlog.

## Criterios de aceptación de fase 1

- `.txt` y `.docx` aportan contenido con referencias de origen.
- El modelo local produce JSON válido; el programa rechaza estructura incompleta o inválida.
- El Word generado conserva portada, imágenes, estilos, secciones, tablas y pie SIPECOM de la plantilla aprobada.
- El informe marca hechos faltantes, suposiciones y contradicciones observables.
- El modo público bloquea documentos con pendientes o datos no confirmados.
- Una demostración ficticia puede renderizarse sin instalar un modelo local.
