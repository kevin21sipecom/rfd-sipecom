"""Renderizador OOXML que preserva la identidad visual de la plantilla SIPECOM aprobada.

Clona párrafos y tablas modelo de la plantilla (estilos, numeración de títulos, bordes) y
construye los ocho capítulos del RFD v2. El índice se inserta como campo TOC para que Word
lo actualice con números de página (ver revision.py).
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from .schema import validar_estructura

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DC = "http://purl.org/dc/elements/1.1/"
NS = {"w": W, "dc": DC}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

POR_DESIGNAR = "Por designar"
PENDIENTE = "Pendiente"
POR_ESTIMAR = "Por estimar"


def tag(nombre: str) -> str:
    return f"{{{W}}}{nombre}"


def texto(elemento: etree._Element) -> str:
    return "".join(elemento.xpath(".//w:t/text()", namespaces=NS))


def _llenar_run(run: etree._Element, valor: str) -> None:
    """Escribe el texto en el run; los saltos de línea se convierten en <w:br/>."""
    for i, linea in enumerate(valor.split("\n")):
        if i:
            etree.SubElement(run, tag("br"))
        t = etree.SubElement(run, tag("t"))
        t.text = linea
        t.set(XML_SPACE, "preserve")


def poner_texto(elemento: etree._Element, valor: str) -> None:
    """Reemplaza el texto del primer párrafo del elemento, conservando el formato del primer run."""
    parrafo = elemento if elemento.tag == tag("p") else elemento.find(".//w:p", NS)
    if parrafo is None:
        raise ValueError("No se encontró un párrafo editable en la plantilla.")
    runs = parrafo.findall("w:r", NS)
    rpr = deepcopy(runs[0].find("w:rPr", NS)) if runs and runs[0].find("w:rPr", NS) is not None else None
    for r in parrafo.findall(".//w:r", NS):
        r.getparent().remove(r)
    for otro in parrafo.xpath(".//w:hyperlink|.//w:bookmarkStart|.//w:bookmarkEnd", namespaces=NS):
        otro.getparent().remove(otro)
    run = etree.SubElement(parrafo, tag("r"))
    if rpr is not None:
        run.append(rpr)
    _llenar_run(run, valor)
    # Las demás líneas de la celda sobran: el valor completo vive en el primer párrafo.
    if elemento.tag != tag("p"):
        for extra in elemento.findall("w:p", NS)[1:]:
            elemento.remove(extra)


def parrafo_de(muestra: etree._Element, valor: str, negrita: bool = False) -> etree._Element:
    """Clona propiedades de párrafo y del primer run, sin bookmarks ni texto viejo."""
    p = deepcopy(muestra)
    ppr = p.find("w:pPr", NS)
    run = p.find("w:r", NS)
    rpr = deepcopy(run.find("w:rPr", NS)) if run is not None and run.find("w:rPr", NS) is not None else None
    for hijo in list(p):
        if hijo is not ppr:
            p.remove(hijo)
    nuevo = etree.SubElement(p, tag("r"))
    if negrita:
        if rpr is None:
            rpr = etree.Element(tag("rPr"))
        if rpr.find("w:b", NS) is None:
            rpr.insert(0, etree.Element(tag("b")))
    if rpr is not None:
        nuevo.append(rpr)
    _llenar_run(nuevo, valor)
    return p


def parrafo_mixto(muestra: etree._Element, partes: list[tuple[str, bool]]) -> etree._Element:
    """Párrafo con varios tramos, p. ej. un rótulo en negrita seguido de texto normal."""
    p = parrafo_de(muestra, partes[0][0], partes[0][1])
    base = p.find("w:r", NS)
    for valor, negrita in partes[1:]:
        run = deepcopy(base)
        for hijo in run.findall("w:t", NS) + run.findall("w:br", NS):
            run.remove(hijo)
        rpr = run.find("w:rPr", NS)
        b = rpr.find("w:b", NS) if rpr is not None else None
        if not negrita and b is not None:
            rpr.remove(b)
        elif negrita and b is None:
            if rpr is None:
                rpr = etree.SubElement(run, tag("rPr"))
                run.insert(0, rpr)
            rpr.insert(0, etree.Element(tag("b")))
        _llenar_run(run, valor)
        p.append(run)
    return p


def tabla_de(muestra: etree._Element, filas: list[list[str]], encabezado: list[str] | None = None) -> etree._Element:
    tabla = deepcopy(muestra)
    trs = tabla.findall("w:tr", NS)
    if len(trs) < 2:
        raise ValueError("Tabla modelo sin fila de datos.")
    if encabezado:
        for celda, valor in zip(trs[0].findall("w:tc", NS), encabezado):
            poner_texto(celda, valor)
    prototipo = deepcopy(trs[1])
    for tr in trs[1:]:
        tabla.remove(tr)
    for valores in filas:
        tr = deepcopy(prototipo)
        celdas = tr.findall("w:tc", NS)
        if len(valores) != len(celdas):
            raise ValueError(f"La tabla espera {len(celdas)} columnas y recibió {len(valores)}.")
        for celda, valor in zip(celdas, valores):
            poner_texto(celda, str(valor))
        tabla.append(tr)
    return tabla


def _campo(tipo: str) -> etree._Element:
    run = etree.Element(tag("r"))
    etree.SubElement(run, tag("fldChar")).set(tag("fldCharType"), tipo)
    return run


def actualizar_toc(sdt: etree._Element, entradas: list[tuple[str, str]]) -> None:
    """Reemplaza el índice por un campo TOC cuyo resultado provisional son las entradas dadas."""
    contenido = sdt.find("w:sdtContent", NS)
    if contenido is None:
        return
    antiguos = list(contenido)
    estilos: dict[str, etree._Element] = {}
    for item in antiguos:
        s = item.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NS)
        if s and s[0] in {"TDC1", "TDC2", "TDC3"} and s[0] not in estilos:
            estilos[s[0]] = item
    if len(estilos) < 2 or not entradas:
        return
    estilos.setdefault("TDC3", estilos["TDC2"])
    for item in antiguos:
        contenido.remove(item)
    contenido.append(parrafo_de(antiguos[0], "Contenido"))
    parrafos = [parrafo_de(estilos[e], t) for e, t in entradas]
    primero = parrafos[0]
    posicion = list(primero).index(primero.find("w:r", NS))
    instruccion = etree.Element(tag("r"))
    instr = etree.SubElement(instruccion, tag("instrText"))
    # Capítulos y secciones: los «Flujo propuesto» de nivel 3 alargarían el índice a más de una página.
    instr.text = ' TOC \\o "1-2" \\h \\z \\u '
    instr.set(XML_SPACE, "preserve")
    for i, run in enumerate([_campo("begin"), instruccion, _campo("separate")]):
        primero.insert(posicion + i, run)
    parrafos[-1].append(_campo("end"))
    for p in parrafos:
        contenido.append(p)


def _portada(cuerpo: etree._Element, parrafos: list[etree._Element], tablas: list[etree._Element], d: dict) -> None:
    campos = {
        "(AA-RFDN)": f"({d['codigo']})",
        "[Nombre del requerimiento]": d["titulo"],
        "[Nombre del cliente]": d["cliente"].upper(),
        "[DD/MMM/AAAA]": d["fecha"],
    }
    for p in parrafos:
        original = texto(p).strip()
        if original in campos:
            poner_texto(p, campos[original])
    r = d["responsables"]
    version = d.get("version") or "0.1"
    filas = [[r["autor"] or "SIPECOM", "Análisis funcional", "0.1", d["fecha"], "Elaboración para revisión funcional"]]
    filas += [[r["autor"] or "SIPECOM", "Análisis funcional", h["version"], h["fecha"], h["descripcion"]] for h in d.get("historial", [])]
    filas.append([r["revisor"] or POR_DESIGNAR, "Revisor", "—", PENDIENTE, "Validación del alcance"])
    historial = tabla_de(tablas[0], filas)
    aprobacion = tabla_de(tablas[1], [
        [r["aprobador_sipecom"] or POR_DESIGNAR, "SIPECOM", version, PENDIENTE, "Revisa", PENDIENTE],
        [r["aprobador_cliente"] or POR_DESIGNAR, d["cliente"], version, PENDIENTE, "Aprueba", PENDIENTE],
    ])
    cuerpo.replace(tablas[0], historial)
    cuerpo.replace(tablas[1], aprobacion)


def numeracion_por_capitulo(numbering: etree._Element, capitulos: int = 8) -> dict[int, str]:
    """Crea una instancia de numeración de títulos por capítulo (N.1, N.1.1) a partir de la del Capítulo 2.

    La plantilla sólo define listas para los capítulos 1 y 2; los títulos 2 y 3 de los demás
    capítulos continuarían la numeración anterior. El nivel 0 empieza en el número del capítulo.
    """
    base_id = numbering.xpath('//w:num[@w:numId="4"]/w:abstractNumId/@w:val', namespaces=NS)
    if not base_id:
        return {}
    base = numbering.xpath(f'//w:abstractNum[@w:abstractNumId="{base_id[0]}"]', namespaces=NS)[0]
    ultimo_abstracto = numbering.findall("w:abstractNum", NS)[-1]
    sig_abstracto = max(int(x) for x in numbering.xpath("//w:abstractNum/@w:abstractNumId", namespaces=NS)) + 1
    sig_num = max(int(x) for x in numbering.xpath("//w:num/@w:numId", namespaces=NS)) + 1
    mapa: dict[int, str] = {}
    # Word no aplica startOverride a un nivel que ningún párrafo usa (Título 1 no está numerado),
    # así que cada capítulo recibe su propia definición abstracta con el nivel 0 iniciando en N.
    for capitulo in range(capitulos, 0, -1):
        abstracto = deepcopy(base)
        abstracto.set(tag("abstractNumId"), str(sig_abstracto))
        for nodo in abstracto.xpath("./w:nsid|./w:tmpl|./w:styleLink|./w:numStyleLink", namespaces=NS):
            abstracto.remove(nodo)
        etree.SubElement(abstracto, tag("nsid")).set(tag("val"), f"{0x5F1E0000 + sig_abstracto:08X}")
        abstracto.insert(0, abstracto[-1])
        inicio = abstracto.xpath('./w:lvl[@w:ilvl="0"]/w:start', namespaces=NS)
        if inicio:
            inicio[0].set(tag("val"), str(capitulo))
        ultimo_abstracto.addnext(abstracto)
        num = etree.SubElement(numbering, tag("num"))
        num.set(tag("numId"), str(sig_num))
        etree.SubElement(num, tag("abstractNumId")).set(tag("val"), str(sig_abstracto))
        mapa[capitulo] = str(sig_num)
        sig_abstracto += 1
        sig_num += 1
    return mapa


def _numerar(p: etree._Element, num_id: str | None) -> etree._Element:
    if num_id:
        for nodo in p.xpath("./w:pPr/w:numPr/w:numId", namespaces=NS):
            nodo.set(tag("val"), num_id)
    return p


def _cuerpo(parrafos: list[etree._Element], tablas: list[etree._Element], d: dict,
            numeros: dict[int, str] | None = None) -> tuple[list[etree._Element], list[tuple[str, str]]]:
    bloques: list[etree._Element] = []
    toc: list[tuple[str, str]] = []
    capitulo, seccion, subseccion, texto_normal = parrafos[51], parrafos[52], parrafos[66], parrafos[53]
    lista, etiqueta = parrafos[68], parrafos[67]
    numeros = numeros or {}
    actual = [0]

    def h1(muestra: etree._Element, valor: str | None = None) -> None:
        valor = texto(muestra).strip() if valor is None else valor
        actual[0] += 1
        bloques.append(parrafo_de(muestra, valor))
        toc.append(("TDC1", valor))

    def h2(valor: str) -> None:
        bloques.append(_numerar(parrafo_de(seccion, valor), numeros.get(actual[0])))
        toc.append(("TDC2", valor))

    def h3(valor: str) -> None:
        bloques.append(_numerar(parrafo_de(subseccion, valor), numeros.get(actual[0])))

    def p(valor: str, negrita: bool = False, muestra: etree._Element | None = None) -> None:
        bloques.append(parrafo_de(muestra if muestra is not None else texto_normal, valor, negrita))

    def ps(valores: list[str], defecto: str = "Por confirmar.") -> None:
        for v in [x for x in valores if x.strip()] or [defecto]:
            p(v)

    def li(valores: list[str], defecto: str = "Por confirmar.") -> None:
        for v in [x for x in valores if x.strip()] or [defecto]:
            bloques.append(parrafo_de(lista, v))

    def t(i: int, filas: list[list[str]], encabezado: list[str] | None = None) -> None:
        bloques.append(tabla_de(tablas[i], filas, encabezado))

    # Capítulo 1
    h1(capitulo)
    h2("Justificación")
    ps(d["justificacion"])
    h2("Objetivo")
    ps([d["objetivo"]])
    h2("Alcance del proyecto")
    ps(d["alcance"]["introduccion"], defecto=texto(parrafos[57]))
    t(2, [[a["id"], a["descripcion"]] for a in d["alcance"]["items"]] or [["RF-01", "Por confirmar."]])
    if d["alcance"]["cierre"].strip():
        p(d["alcance"]["cierre"])

    # Capítulo 2
    h1(parrafos[59])
    h2("Descripción del proceso actual (AS-IS)")
    if d["tipo_proyecto"] == "nuevo" and not "".join(d["proceso_actual"]).strip():
        p("No aplica: se trata de una solución nueva sin un proceso previo equivalente.")
    else:
        ps(d["proceso_actual"])
    for s in d["secciones_generales"]:
        h2(s["titulo"])
        ps(s["parrafos"])
    for r in d["requerimientos"]:
        h2(r["nombre"] or r["id"])
        ps(r["parrafos"])
        if r["referencia"].strip():
            p(r["referencia"])
        for i, e in enumerate(r["elementos"], 1):
            p(f"{i}. {e['titulo']}", negrita=True)
            p(e["detalle"])
        if r["flujo"]:
            h3("Flujo propuesto")
            t(3, [[str(x["numero"]), x["actor"], x["componente"], x["accion"]] for x in r["flujo"]])
        if r["criterios_aceptacion"]:
            p("Criterios de aceptación", muestra=etiqueta)
            li(r["criterios_aceptacion"])
    c = d["componentes"]
    if c["items"]:
        h2(c["titulo"] or "Adecuaciones de los componentes existentes")
        if c["introduccion"].strip():
            p(c["introduccion"])
        filas = [[f"{x['componente']}\n{x['ubicacion']}".strip(), x["adecuacion"]] for x in c["items"]]
        t(4, filas, ["Componente", "Adecuación funcional"])

    # Capítulo 3
    h1(parrafos[72])
    p(d["prerrequisitos"]["introduccion"] or texto(parrafos[73]), muestra=parrafos[73])
    li(d["prerrequisitos"]["items"])
    if d["definiciones"]:
        h2("Definiciones requeridas para construcción")
        for x in d["definiciones"]:
            p(f"{x['id']} — {x['titulo']}", negrita=True)
            p(x["descripcion"])
    preguntas = d.get("preguntas_cliente", [])
    if preguntas:
        h2("Preguntas para el cliente")
        p("Las siguientes preguntas deberán responderse para completar las definiciones anteriores y cerrar el alcance. "
          "Sus respuestas se incorporarán en una nueva versión de este documento.")
        for i, x in enumerate(preguntas, 1):
            bloques.append(parrafo_mixto(texto_normal, [(f"{i}. {x['tema']}: ", True), (f"{x['contexto']} {x['pregunta']}".strip(), False)]))

    # Capítulo 4
    h1(parrafos[76])
    li(d["restricciones"])

    # Capítulo 5
    h1(parrafos[79])
    p("Durante la ejecución del proyecto se generarán los siguientes entregables, conforme a las fases y responsabilidades acordadas.",
      muestra=parrafos[80])
    t(4, [[x["fase"], x["entregable"]] for x in d["entregables"]] or [["Por definir", "Por definir"]])

    # Capítulo 6
    e = d["esfuerzo"]
    h1(parrafos[81])
    if e["introduccion"].strip():
        p(e["introduccion"])
    filas = [[x["actividad"], str(x["horas"]) if x["horas"] is not None else POR_ESTIMAR] for x in e["actividades"]]
    filas.append(["TOTAL", str(e["total_horas"]) if e["total_horas"] is not None else POR_ESTIMAR])
    t(5, filas)
    notas = list(e["notas"])
    if e["total_horas"] is not None:
        notas.insert(0, f"La propuesta tiene un esfuerzo total de {e['total_horas']} horas hombre.")
    if e["duracion"].strip():
        notas.insert(1 if e["total_horas"] is not None else 0, f"La duración estimada del proyecto es de {e['duracion']}.")
    li(notas, defecto="El esfuerzo y la duración se establecerán sobre el alcance aprobado.")

    # Capítulo 7
    r = d["responsables"]
    h1(parrafos[85], "Capítulo 7: Firmas de Aceptación")
    bloques.append(deepcopy(parrafos[86]))  # conserva tabs de alineación del rótulo SIPECOM
    firmas = deepcopy(tablas[6])
    for celda, valor in zip(firmas.findall("w:tr", NS)[2].findall("w:tc", NS),
                            [f"Equipo de proyecto\n{r['autor'] or 'Nombre por designar'}",
                             f"Responsable técnico\n{r['revisor'] or 'Nombre por designar'}"]):
        poner_texto(celda, valor)
    for celda in firmas.findall("w:tr", NS)[3].findall("w:tc", NS):
        poner_texto(celda, f"Fecha: {PENDIENTE}")
    bloques.append(firmas)
    p(d["cliente"].upper(), muestra=parrafos[87])
    aprobacion = deepcopy(tablas[7])
    for celda, valor in zip(aprobacion.findall("w:tr", NS)[2].findall("w:tc", NS),
                            [f"Responsable del proyecto\n{r['aprobador_sipecom'] or 'Nombre por designar'}",
                             f"Responsable de negocio\n{r['aprobador_cliente'] or 'Nombre por designar'}"]):
        poner_texto(celda, valor)
    for celda in aprobacion.findall("w:tr", NS)[3].findall("w:tc", NS):
        poner_texto(celda, f"Fecha: {PENDIENTE}")
    bloques.append(aprobacion)

    # Capítulo 8
    h1(parrafos[88])
    p("Documentos y componentes de referencia utilizados para definir el alcance funcional.", muestra=parrafos[89])
    for a in d["anexos"]:
        p(f"{a['id']} — {a['nombre']}", negrita=True)
        if a["uso"].strip():
            p(a["uso"])
    if not d["anexos"]:
        p("No se registran anexos.")
    return bloques, toc


def crear_docx(datos: dict, plantilla: Path, salida: Path) -> None:
    validar_estructura(datos)
    if not plantilla.is_file():
        raise FileNotFoundError(f"No se encontró la plantilla: {plantilla}")
    salida.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(plantilla) as origen:
        documento = etree.fromstring(origen.read("word/document.xml"))
        cuerpo = documento.find("w:body", NS)
        if cuerpo is None:
            raise ValueError("Plantilla Word sin cuerpo.")
        parrafos = [e for e in cuerpo if e.tag == tag("p")]
        tablas = [e for e in cuerpo if e.tag == tag("tbl")]
        if len(parrafos) < 91 or len(tablas) != 8 or not texto(parrafos[51]).startswith("Capítulo 1:"):
            raise ValueError("La plantilla no coincide con la versión SIPECOM aprobada.")
        inicio = next(i for i, e in enumerate(cuerpo) if e is parrafos[51])
        indice = next((e for e in list(cuerpo)[:inicio] if e.tag == tag("sdt") and "Contenido" in texto(e)), None)
        seccion_final = deepcopy(list(cuerpo)[-1])
        numbering = etree.fromstring(origen.read("word/numbering.xml"))
        bloques, toc = _cuerpo(parrafos, tablas, datos, numeracion_por_capitulo(numbering))
        numbering_xml = etree.tostring(numbering, xml_declaration=True, encoding="UTF-8", standalone="yes")
        _portada(cuerpo, parrafos, tablas, datos)
        if indice is not None:
            actualizar_toc(indice, toc)
        inicio = next(i for i, e in enumerate(cuerpo) if e is parrafos[51])
        for e in list(cuerpo)[inicio:]:
            cuerpo.remove(e)
        # El salto de página tras el índice deja una página en blanco cuando el índice llena la suya;
        # «salto de página anterior» en el Capítulo 1 consigue lo mismo sin ese riesgo.
        if indice is not None:
            siguiente = indice.getnext()
            if (siguiente is not None and siguiente.tag == tag("p") and not texto(siguiente).strip()
                    and siguiente.xpath(".//w:br[@w:type='page']", namespaces=NS) and not siguiente.xpath(".//w:sectPr", namespaces=NS)):
                cuerpo.remove(siguiente)
                ppr = bloques[0].find("w:pPr", NS)
                if ppr is None:
                    ppr = etree.SubElement(bloques[0], tag("pPr"))
                    bloques[0].insert(0, ppr)
                if ppr.find("w:pageBreakBefore", NS) is None:
                    estilo = ppr.find("w:pStyle", NS)
                    ppr.insert(1 if estilo is not None else 0, etree.Element(tag("pageBreakBefore")))
        for e in bloques:
            cuerpo.append(e)
        cuerpo.append(seccion_final)
        documento_xml = etree.tostring(documento, xml_declaration=True, encoding="UTF-8", standalone="yes")
        pie = etree.fromstring(origen.read("word/footer2.xml"))
        titulo_pie = f"{datos['codigo']} - {datos['titulo']}"
        if len(titulo_pie) > 72:
            titulo_pie = datos["codigo"]
        for nodo in pie.xpath(".//w:t", namespaces=NS):
            if "Plantilla RFD SIPECOM" in (nodo.text or ""):
                nodo.text = titulo_pie
        pie_xml = etree.tostring(pie, xml_declaration=True, encoding="UTF-8", standalone="yes")
        core = etree.fromstring(origen.read("docProps/core.xml"))
        for nombre, valor in [("title", datos["titulo"]), ("subject", f"RFD {datos['codigo']}"), ("creator", "SIPECOM")]:
            nodo = core.find(f"dc:{nombre}", NS)
            if nodo is not None:
                nodo.text = valor
        core_xml = etree.tostring(core, xml_declaration=True, encoding="UTF-8", standalone="yes")
        reemplazos = {"word/document.xml": documento_xml, "word/footer2.xml": pie_xml, "docProps/core.xml": core_xml,
                      "word/numbering.xml": numbering_xml}
        with ZipFile(salida, "w") as destino:
            for item in origen.infolist():
                destino.writestr(item, reemplazos.get(item.filename, origen.read(item.filename)))


def texto_docx(ruta: Path) -> str:
    with ZipFile(ruta) as z:
        documento = etree.fromstring(z.read("word/document.xml"))
    return "\n".join(texto(p) for p in documento.iter(tag("p")))
