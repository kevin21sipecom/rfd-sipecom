"""Lectura de transcripciones y contexto con referencias de origen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

EXTENSIONES = {".txt", ".md", ".docx", ".pptx", ".pdf", ".xlsx", ".xlsm"}
MAX_CARACTERES = 120_000
# Los modelos de las CLIs admiten contextos amplios (~4 caracteres por token); 120 000 queda para OpenCode.
MAX_CARACTERES_CLAUDE = 450_000


def limite_para(proveedor: str) -> int:
    # OpenCode puede usar modelos gratuitos de 200k tokens: se mantiene el límite conservador.
    return MAX_CARACTERES if proveedor == "opencode" else MAX_CARACTERES_CLAUDE


@dataclass(frozen=True)
class Fuente:
    id: str
    nombre: str
    categoria: str
    contenido: str

    def para_prompt(self) -> str:
        return f"[FUENTE {self.id} | {self.categoria} | {self.nombre}]\n{self.contenido}"


def _leer_txt(ruta: Path) -> str:
    raw = ruta.read_bytes()
    try:
        contenido = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        contenido = raw.decode("cp1252")
    return "\n".join(f"L{i}: {line.strip()}" for i, line in enumerate(contenido.splitlines(), 1) if line.strip())


def _leer_docx(ruta: Path) -> str:
    documento = Document(ruta)
    partes: list[str] = []
    p = t = 0
    for bloque in documento.iter_inner_content():
        if isinstance(bloque, Paragraph):
            p += 1
            texto = bloque.text.strip()
            if texto:
                partes.append(f"P{p}: {texto}")
        elif isinstance(bloque, Table):
            t += 1
            for ri, fila in enumerate(bloque.rows, 1):
                for ci, celda in enumerate(fila.cells, 1):
                    texto = " ".join(x.text.strip() for x in celda.paragraphs if x.text.strip())
                    if texto:
                        partes.append(f"T{t}F{ri}C{ci}: {texto}")
    return "\n".join(partes)


def _leer_pptx(ruta: Path) -> str:
    from pptx import Presentation

    partes: list[str] = []
    for d, diapositiva in enumerate(Presentation(ruta).slides, 1):
        for forma in diapositiva.shapes:
            if forma.has_text_frame:
                for parrafo in forma.text_frame.paragraphs:
                    texto = "".join(r.text for r in parrafo.runs).strip()
                    if texto:
                        partes.append(f"D{d}: {texto}")
            if getattr(forma, "has_table", False) and forma.has_table:
                for ri, fila in enumerate(forma.table.rows, 1):
                    for ci, celda in enumerate(fila.cells, 1):
                        if celda.text.strip():
                            partes.append(f"D{d}F{ri}C{ci}: {' '.join(celda.text.split())}")
        if diapositiva.has_notes_slide:
            notas = diapositiva.notes_slide.notes_text_frame.text.strip()
            if notas:
                partes.append(f"D{d}N: {' '.join(notas.split())}")
    return "\n".join(partes)


def _leer_pdf(ruta: Path) -> str:
    """Texto por página (Pg3L12: …). Los PDF escaneados no tienen capa de texto y quedan vacíos."""
    from pypdf import PdfReader

    partes: list[str] = []
    for n, pagina in enumerate(PdfReader(ruta).pages, 1):
        lineas = [x.strip() for x in (pagina.extract_text() or "").splitlines() if x.strip()]
        partes.extend(f"Pg{n}L{i}: {linea}" for i, linea in enumerate(lineas, 1))
    return "\n".join(partes)


def _leer_excel(ruta: Path) -> str:
    """Cada hoja con su nombre y cada fila con marca H{hoja}F{fila}; celdas vacías omitidas.

    Se leen los valores calculados (data_only): las fórmulas aparecen con su resultado. Las hojas ocultas
    se incluyen y se marcan, porque en matrices internas suelen guardar datos de referencia."""
    from openpyxl import load_workbook

    libro = load_workbook(ruta, read_only=True, data_only=True)
    partes: list[str] = []
    for h, hoja in enumerate(libro.worksheets, 1):
        # Algunos generadores declaran dimensión A1; en modo lectura openpyxl la respetaría y omitiría las demás filas.
        hoja.reset_dimensions()
        estado = "" if hoja.sheet_state == "visible" else " (oculta)"
        partes.append(f"H{h}: hoja «{hoja.title}»{estado}")
        for f, fila in enumerate(hoja.iter_rows(values_only=True), 1):
            # Las celdas vacías conservan su lugar para que cada valor siga siendo el de su columna.
            celdas = [" ".join(str(v).split()) if v is not None else "" for v in fila]
            while celdas and not celdas[-1]:
                celdas.pop()
            if any(celdas):
                partes.append(f"H{h}F{f}: {' | '.join(celdas)}")
    libro.close()
    return "\n".join(partes)


# Markdown se lee como texto plano: los encabezados, tablas y listas ya son legibles para el modelo.
_LECTORES = {".txt": _leer_txt, ".md": _leer_txt, ".docx": _leer_docx, ".pptx": _leer_pptx, ".pdf": _leer_pdf,
             ".xlsx": _leer_excel, ".xlsm": _leer_excel}


MAX_ESTILO = 60_000


def leer_documento(ruta: Path) -> str:
    ruta = ruta.expanduser().resolve()
    if not ruta.is_file():
        raise FileNotFoundError(ruta)
    sufijo = ruta.suffix.lower()
    if sufijo == ".ppt":
        raise ValueError(f"{ruta.name} usa el formato antiguo .ppt; ábralo en PowerPoint y guárdelo como .pptx.")
    if sufijo == ".xls":
        raise ValueError(f"{ruta.name} usa el formato antiguo .xls; ábralo en Excel y guárdelo como .xlsx.")
    if sufijo not in EXTENSIONES:
        raise ValueError(f"Formato no admitido: {ruta.name}; use .txt, .md, .docx, .pptx, .pdf o .xlsx.")
    contenido = _LECTORES[sufijo](ruta)
    if not contenido.strip():
        if sufijo in (".xlsx", ".xlsm"):
            raise ValueError(f"{ruta.name} no tiene celdas con texto o valores.")
        if sufijo == ".pdf":
            raise ValueError(f"{ruta.name} no tiene texto seleccionable (parece escaneado); aplíquele OCR o expórtelo a Word.")
        raise ValueError(f"El archivo no contiene texto extraíble: {ruta.name}")
    return contenido


def cargar_fuentes(
    transcripciones: list[Path],
    contextos: list[Path],
    estilos: list[Path] | None = None,
    limite: int = MAX_CARACTERES,
) -> list[Fuente]:
    """Fuentes de contenido (F01…) y referencias de estilo (E01…), que no aportan hechos al RFD."""
    estilos = estilos or []
    if not transcripciones and not contextos:
        raise ValueError("Se requiere al menos un archivo: una transcripción o un documento de contexto.")
    archivos = [("transcripcion", p) for p in transcripciones] + [("contexto", p) for p in contextos]
    nombres = [p.name.lower() for _, p in archivos + [("estilo", p) for p in estilos]]
    if len(nombres) != len(set(nombres)):
        raise ValueError("Los archivos deben tener nombres distintos para mantener referencias inequívocas.")
    fuentes = [Fuente(f"F{i:02}", r.name, c, leer_documento(r)) for i, (c, r) in enumerate(archivos, 1)]
    total = sum(len(f.contenido) for f in fuentes)
    if total > limite:
        raise ValueError(
            f"Las fuentes contienen {total:,} caracteres; el límite para este motor es {limite:,}. "
            "Quite documentos que no aporten al alcance o divida el RFD."
        )
    for i, ruta in enumerate(estilos, 1):
        fuentes.append(Fuente(f"E{i:02}", ruta.name, "estilo", leer_documento(ruta)[:MAX_ESTILO]))
    return fuentes
