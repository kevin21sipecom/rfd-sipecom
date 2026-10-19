"""Maquetas de UI dentro de un Word: cada imagen del cuerpo con el título y el texto bajo el que aparece.

Sólo se leen las imágenes del cuerpo (word/document.xml): logos y franjas viven en encabezados y pies.
Los íconos (pocos bytes) y las repetidas se descartan. El índice queda en «imagenes.json» junto a las imágenes.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W, "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
INDICE = "imagenes.json"
# Formatos que los modelos aceptan como imagen; EMF/WMF y similares no se pueden enviar.
TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MINIMO_BYTES = 4_000
MAX_CONTEXTO = 300
RE_ARCHIVO = re.compile(r"^img_\d{2,3}\.(?:png|jpe?g|gif|webp)$")


def directorio_ui(salidas: Path, codigo: str) -> Path:
    """Maquetas y capturas de un RFD: compartidas por todas sus versiones (mismo código)."""
    return salidas / "_ui" / (re.sub(r"[^\w.\-]+", "_", codigo).strip("._") or "RFD")


def agregar_imagen(destino: Path, datos: bytes, titulo: str, contexto: str, origen: str, extension: str = ".png",
                   reemplazar: bool = False) -> dict[str, Any]:
    """Suma una imagen al índice (o devuelve la existente si ya estaba) y la guarda como img_NN.

    Con `reemplazar`, una imagen con el mismo título (la captura de una ventana del prototipo) se actualiza en su lugar.
    """
    indice = leer_indice(destino)
    huella = hashlib.sha1(datos).hexdigest()
    if previa := next((x for x in indice if x["sha1"] == huella), None):
        return previa
    destino.mkdir(parents=True, exist_ok=True)
    if reemplazar and (previa := next((x for x in indice if x["titulo"] == titulo), None)):
        (destino / previa["archivo"]).write_bytes(datos)
        previa.update(origen=origen, bytes=len(datos), sha1=huella)
        (destino / INDICE).write_text(json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
        return previa
    entrada = {"archivo": f"img_{len(indice) + 1:02}{extension}", "titulo": titulo, "contexto": contexto[:MAX_CONTEXTO],
               "origen": origen, "bytes": len(datos), "sha1": huella}
    (destino / entrada["archivo"]).write_bytes(datos)
    indice.append(entrada)
    (destino / INDICE).write_text(json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
    return entrada


def leer_indice(destino: Path) -> list[dict[str, Any]]:
    try:
        return json.loads((destino / INDICE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _niveles_de_titulo(z: ZipFile) -> dict[str, int]:
    """styleId → nivel de título (1 = «heading 1»), por nombre del estilo o por su nivel de esquema."""
    try:
        estilos = etree.fromstring(z.read("word/styles.xml"))
    except KeyError:
        return {}
    niveles: dict[str, int] = {}
    for s in estilos.findall("w:style", NS):
        nombre = s.xpath("string(w:name/@w:val)", namespaces=NS).lower()
        esquema = s.xpath("string(w:pPr/w:outlineLvl/@w:val)", namespaces=NS)
        if m := re.fullmatch(r"heading (\d)", nombre):
            niveles[s.get(f"{{{W}}}styleId")] = int(m.group(1))
        elif esquema.isdigit() and int(esquema) < 9:
            niveles[s.get(f"{{{W}}}styleId")] = int(esquema) + 1
    return niveles


def _texto(p: etree._Element) -> str:
    return " ".join("".join(p.xpath(".//w:t/text()", namespaces=NS)).split())


def extraer_imagenes(docx: Path, destino: Path, minimo_bytes: int = MINIMO_BYTES) -> list[dict[str, Any]]:
    """Agrega al índice de `destino` las maquetas de `docx` y devuelve el índice completo."""
    indice = leer_indice(destino)
    try:
        z = ZipFile(docx)
    except (BadZipFile, OSError):
        return indice
    with z:
        try:
            cuerpo = etree.fromstring(z.read("word/document.xml"))
            rels = etree.fromstring(z.read("word/_rels/document.xml.rels"))
        except (KeyError, etree.XMLSyntaxError):
            return indice
        objetivos = {r.get("Id"): posixpath.normpath(posixpath.join("word", r.get("Target", "")))
                     for r in rels.findall("rel:Relationship", NS) if r.get("TargetMode") != "External"}
        niveles = _niveles_de_titulo(z)
        vistos = {x["sha1"] for x in indice}
        nuevas = 0
        titulos: list[str] = []
        contexto = ""
        for p in cuerpo.iter(f"{{{W}}}p"):
            estilo = p.xpath("string(w:pPr/w:pStyle/@w:val)", namespaces=NS)
            esquema = p.xpath("string(w:pPr/w:outlineLvl/@w:val)", namespaces=NS)
            nivel = niveles.get(estilo) or (int(esquema) + 1 if esquema.isdigit() and int(esquema) < 9 else None)
            texto = _texto(p)
            if nivel and texto:
                titulos = titulos[:nivel - 1] + [texto]
                contexto = ""
                continue
            for rid in p.xpath(".//a:blip/@r:embed", namespaces=NS):
                ruta = objetivos.get(rid, "")
                extension = Path(ruta).suffix.lower()
                if extension not in TIPOS:
                    continue
                try:
                    datos = z.read(ruta)
                except KeyError:
                    continue
                huella = hashlib.sha1(datos).hexdigest()
                if len(datos) < minimo_bytes or huella in vistos:
                    continue
                vistos.add(huella)
                nuevas += 1
                agregar_imagen(destino, datos, " › ".join(titulos), contexto, Path(docx).name, extension)
            if texto:
                contexto = texto
    return leer_indice(destino) if nuevas else indice


def tipo_de(archivo: str | Path) -> str:
    return TIPOS.get(Path(archivo).suffix.lower(), "application/octet-stream")
