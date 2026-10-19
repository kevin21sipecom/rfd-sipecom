"""Pruebas del generador de RFD.

Las marcadas con `claude` llaman a la CLI real (requieren sesión iniciada y consumen uso).
Omítalas con: pytest -m "not claude". Modelo de prueba: variable RFD_MODELO_TEST (por defecto haiku).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from zipfile import ZipFile

import pytest
from lxml import etree

from generador_rfd import servidor
from generador_rfd.fuentes import Fuente, cargar_fuentes, leer_documento
from generador_rfd.modelo import analizar_fuentes, comando_claude, crear_prompt, temas_de_codigo
from generador_rfd.pipeline import publicar, terminos_ajenos
from generador_rfd.proyecto import inventario_repositorios
from generador_rfd.schema import SCHEMA, auditar_texto_final, normalizar
from generador_rfd.word import NS, texto_docx

RAIZ = Path(__file__).resolve().parent.parent
EJEMPLOS = RAIZ / "ejemplos"
MODELO = os.environ.get("RFD_MODELO_TEST", "haiku")
CLAUDE = shutil.which("claude")
requiere_claude = pytest.mark.skipif(not CLAUDE, reason="Claude Code CLI no está en PATH")


def test_comando_claude_va_aislado_y_sin_meta_esquema():
    comando = comando_claude("claude", "sonnet", SCHEMA)
    for opcion in ("-p", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert opcion in comando
    assert comando[comando.index("--tools") + 1] == ""
    assert comando[comando.index("--setting-sources") + 1] == ""
    esquema = json.loads(comando[comando.index("--json-schema") + 1])
    assert "$schema" not in esquema
    assert esquema["required"] == SCHEMA["required"]


def test_varios_archivos_y_referencias_de_estilo():
    fuentes = cargar_fuentes(
        [EJEMPLOS / "transcripcion_demo.txt"],
        [EJEMPLOS / "contexto_demo.docx", EJEMPLOS / "presentacion_demo.pptx"],
        [EJEMPLOS / "contexto_demo.txt"],
    )
    assert [f.id for f in fuentes] == ["F01", "F02", "F03", "E01"]
    assert [f.categoria for f in fuentes] == ["transcripcion", "contexto", "contexto", "estilo"]
    assert fuentes[2].contenido.startswith("D1:")
    with pytest.raises(ValueError, match="nombres distintos"):
        cargar_fuentes([EJEMPLOS / "transcripcion_demo.txt"], [EJEMPLOS / "transcripcion_demo.txt"])


def test_lee_pdf_y_markdown(tmp_path):
    fuentes = cargar_fuentes([], [EJEMPLOS / "contexto_demo.pdf", EJEMPLOS / "requisitos_demo.md"])
    assert fuentes[0].contenido.startswith("Pg1L1:")
    assert "Proyecto ficticio" in fuentes[0].contenido
    assert "| Solicitudes abiertas por categoría | Semanal | Coordinador |" in fuentes[1].contenido
    vacio = tmp_path / "escaneado.pdf"
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.write(vacio)
    with pytest.raises(ValueError, match="OCR"):
        cargar_fuentes([], [vacio])


def test_lee_excel_con_columnas_y_hojas_ocultas(tmp_path):
    from openpyxl import Workbook

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Requerimientos"
    hoja.append(["ID", "Requerimiento", "Prioridad", "Responsable"])
    hoja.append(["RQ-01", "Consultar saldo", "Alta", "Equipo SAP"])
    hoja.append(["RQ-02", "Exportar PDF", None, "Equipo portal"])
    oculta = libro.create_sheet("Parámetros")
    oculta.append(["Clave", "Valor"])
    oculta.sheet_state = "hidden"
    ruta = tmp_path / "matriz.xlsx"
    libro.save(ruta)
    fuentes = cargar_fuentes([], [ruta])
    texto = fuentes[0].contenido
    assert "H1: hoja «Requerimientos»" in texto and "H2: hoja «Parámetros» (oculta)" in texto
    # La celda vacía de «Prioridad» conserva su columna: «Equipo portal» sigue siendo el responsable.
    assert "H1F3: RQ-02 | Exportar PDF |  | Equipo portal" in texto
    with pytest.raises(ValueError, match="guárdelo como .xlsx"):
        leer_documento(_xls(tmp_path))


def _xls(tmp_path):
    ruta = tmp_path / "viejo.xls"
    ruta.write_bytes(bytes([0xD0, 0xCF, 0x11, 0xE0]))
    return ruta


def test_transcripcion_opcional_si_hay_contexto():
    fuentes = cargar_fuentes([], [EJEMPLOS / "contexto_demo.docx", EJEMPLOS / "presentacion_demo.pptx"])
    assert [f.categoria for f in fuentes] == ["contexto", "contexto"]
    assert "No hay transcripción de reunión" in crear_prompt(fuentes, "", "Cliente", "C-1", "existente", "02/10/2026", None)
    con_reunion = crear_prompt(cargar_fuentes([EJEMPLOS / "transcripcion_demo.txt"], []), "", "C", "C-1", "nuevo", "x", None)
    assert "No hay transcripción de reunión" not in con_reunion
    with pytest.raises(ValueError, match="al menos un archivo"):
        cargar_fuentes([], [])


def test_prompt_separa_estilo_y_analisis():
    fuentes = cargar_fuentes([EJEMPLOS / "transcripcion_demo.txt"], [], [EJEMPLOS / "contexto_demo.txt"])
    prompt = crear_prompt(fuentes, "", "C", "C-1", "nuevo", "x", None, {"F01": {"resumen": "ANALISIS-UNICO"}})
    assert "ANALISIS-UNICO" in prompt
    assert prompt.index("REFERENCIAS DE ESTILO") < prompt.index("FUENTES COMPLETAS")
    assert "[FUENTE E01" not in prompt.split("FUENTES COMPLETAS")[1]
    assert temas_de_codigo({"F01": {"terminos_codigo": ["pedido", "contrato"]}}, None, "") == ["pedido contrato"]
    assert temas_de_codigo({}, None, "precios") == ["precios"]


def test_demo_v2_se_publica_sin_hallazgos_y_numera_por_capitulo(tmp_path):
    datos = json.loads((EJEMPLOS / "rfd_demo.json").read_text(encoding="utf-8"))
    datos["definiciones"] = [{"id": "D-01", "titulo": "Prueba", "descripcion": "Texto.", "evidencias": []}]
    r = publicar(datos, tmp_path / "RFD.docx")
    assert [h.codigo for h in r.hallazgos] == ["definiciones"]
    texto = texto_docx(r.salida)
    assert "Definiciones requeridas para construcción" in texto and "D-01 — Prueba" in texto
    assert "Adecuaciones de los componentes existentes" in texto
    with ZipFile(r.salida) as z:
        documento = etree.fromstring(z.read("word/document.xml"))
        numeracion = etree.fromstring(z.read("word/numbering.xml"))
    assert documento.xpath("count(//w:instrText[contains(., 'TOC')])", namespaces=NS) == 1
    # El título 2 del Capítulo 3 usa una lista cuyo nivel 0 empieza en 3 (→ «3.1.»).
    titulo = documento.xpath("//w:p[.//w:numId and .//w:t[text()='Definiciones requeridas para construcción']]", namespaces=NS)[0]
    num_id = titulo.xpath("string(.//w:numId/@w:val)", namespaces=NS)
    abstracto = numeracion.xpath(f"string(//w:num[@w:numId='{num_id}']/w:abstractNumId/@w:val)", namespaces=NS)
    inicio = numeracion.xpath(f"string(//w:abstractNum[@w:abstractNumId='{abstracto}']/w:lvl[@w:ilvl='0']/w:start/@w:val)", namespaces=NS)
    assert inicio == "3"


def test_revision_detecta_plantilla_y_contenido_heredado():
    fuentes = [Fuente("F01", "a.txt", "contexto", "Portal Contoso pedidos"),
               Fuente("E01", "ref.docx", "estilo", "Banco Northwind aprobó. Banco Northwind usa Swift.")]
    terminos = terminos_ajenos(fuentes, "Contoso")
    assert "Northwind" in terminos and "Contoso" not in terminos
    hallazgos = auditar_texto_final("Texto [Nombre del cliente] y Banco Northwind", terminos)
    assert {h.codigo for h in hallazgos} == {"instrucciones_plantilla", "referencia_heredada"}


def test_inventario_de_varios_repositorios(tmp_path):
    web = tmp_path / "repo-web" / "src" / "app"
    web.mkdir(parents=True)
    (tmp_path / "repo-web" / "angular.json").write_text("{}", encoding="utf-8")
    (web / "pedido.component.ts").write_text("", encoding="utf-8")
    db = tmp_path / "repo-db" / "sp"
    db.mkdir(parents=True)
    (tmp_path / "repo-db" / "README.md").write_text("# Base de datos", encoding="utf-8")
    (db / "p.sql").write_bytes("CREATE PROCEDURE dbo.Ped_Registrar AS SELECT 1".encode("utf-16"))
    inventario = inventario_repositorios(tmp_path)
    assert "2 repositorio(s)" in inventario
    assert "Componentes Angular (1): pedido" in inventario
    assert "dbo.Ped_Registrar" in inventario


def test_comando_codex_aislado_y_eventos(tmp_path):
    from generador_rfd.modelo import comando_codex, eventos_codex

    nube = comando_codex("codex", "gpt-6-luna", "low", tmp_path, tmp_path / "e.json", tmp_path / "r.json")
    for opcion in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--json", "--output-schema"):
        assert opcion in nube
    assert nube[nube.index("--sandbox") + 1] == "read-only"
    assert 'model_reasoning_effort="low"' in nube and "--oss" not in nube
    tokens, error = eventos_codex("\n".join([
        '{"type":"thread.started"}', "texto no JSON",
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":7,"reasoning_output_tokens":3}}',
        '{"type":"error","message":"límite de uso"}',
    ]))
    assert tokens == {"input_tokens": 100, "output_tokens": 7, "reasoning_output_tokens": 3}
    assert error == "límite de uso"


def _rfd_de_nivel() -> dict:
    """RFD sintético que imita las proporciones del RFD de referencia aprobado."""
    frase = lambda n, base="El portal deberá registrar el resultado de la operación": " ".join([base] + ["con trazabilidad completa"] * ((n - len(base.split())) // 3 + 1)).split()[:n]  # noqa: E731
    parrafo = lambda n: " ".join(frase(n, "Se adecuará la consulta del portal para utilizar los datos vigentes")) + "."  # noqa: E731
    criterio = lambda extra="": " ".join(frase(20)) + extra + "."  # noqa: E731
    datos = json.loads((EJEMPLOS / "rfd_demo.json").read_text(encoding="utf-8"))
    datos.update(
        justificacion=[parrafo(70), parrafo(65)],
        objetivo="Adecuar " + " ".join(frase(39)),
        proceso_actual=[parrafo(40)] * 4,
        secciones_generales=[{"titulo": "Integración", "parrafos": [
            parrafo(45), "La integración deberá distinguir una consulta sin resultados, una validación rechazada y una falla de comunicación con el sistema externo."]}],
    )
    datos["alcance"]["items"] = [{"id": a["id"], "descripcion": "Registrar " + " ".join(frase(11))} for a in datos["alcance"]["items"]]
    for r in datos["requerimientos"]:
        r["parrafos"] = [parrafo(40), parrafo(35)]
        r["flujo"] = [{"numero": i, "actor": "Usuario", "componente": "Portal", "accion": "Registra la información requerida del paso"} for i in range(1, 6)]
        r["criterios_aceptacion"] = [criterio() for _ in range(4)] + [criterio(" y no deberá continuar ante un error")]
    datos["prerrequisitos"]["items"] = ["El Cliente deberá " + " ".join(frase(16)) for _ in range(9)]
    datos["restricciones"] = [" ".join(frase(16)) for _ in range(9)]
    datos["anexos"] = [{"id": "F-01", "nombre": "a.docx", "uso": "Interfaz de solicitudes; base de RF-01."}]
    return datos


def test_rubrica_aprueba_nivel_de_referencia_y_rechaza_borrador_pobre():
    from generador_rfd.calidad import evaluar, instrucciones_correccion

    bueno = evaluar(_rfd_de_nivel())
    assert bueno.aprobado(), instrucciones_correccion(bueno)
    pobre = evaluar(json.loads((EJEMPLOS / "rfd_demo.json").read_text(encoding="utf-8")))
    assert not pobre.aprobado()
    fallas = {c.id for c in pobre.fallas}
    assert {"justificacion", "voz_normativa", "RF-01.criterios"} <= fallas
    assert "[RF-01.criterios]" in instrucciones_correccion(pobre)


def test_rubrica_detecta_marcas_de_fuente_y_criterios_cortos():
    from generador_rfd.calidad import evaluar

    datos = _rfd_de_nivel()
    datos["requerimientos"][0]["criterios_aceptacion"] = ["Muestra datos.", "Funciona bien (F01 P12).", "Valida.", "Guarda."]
    fallas = {c.id for c in evaluar(datos).fallas}
    assert {"RF-01.criterios", "sin_marcas"} <= fallas


def _demo_con_preguntas() -> dict:
    datos = json.loads((EJEMPLOS / "rfd_demo.json").read_text(encoding="utf-8"))
    datos["preguntas_cliente"] = [
        {"id": "P-01", "tema": "Países", "contexto": "La especificación incluye cuatro países y otros documentos mencionan dos más.",
         "pregunta": "¿Qué países quedan incluidos en esta entrega?", "relacion": ["D-01"]},
        {"id": "P-02", "tema": "Transición", "contexto": "Hoy los pedidos se registran en Excel y luego se cargan en el sistema.",
         "pregunta": "¿El proceso actual coexistirá con la integración?", "relacion": ["RF-01"]},
    ]
    return datos


def test_cuestionario_y_seccion_de_preguntas(tmp_path):
    from docx import Document

    from generador_rfd.cuestionario import leer_cuestionario

    r = publicar(_demo_con_preguntas(), tmp_path / "RFD.docx")
    texto = texto_docx(r.salida)
    assert "Preguntas para el cliente" in texto and "1. Países: " in texto
    cuestionario = r.salida.with_suffix(".cuestionario.docx")
    assert cuestionario.is_file()
    doc = Document(cuestionario)
    tabla = doc.tables[0]
    assert [c.text for c in tabla.rows[0].cells] == ["N.º", "Tema", "Contexto y pregunta", "Respuesta del cliente"]
    tabla.rows[1].cells[3].text = "Colombia, Chile, Perú y Ecuador."
    tabla.rows[2].cells[3].text = "Pendiente"
    doc.save(cuestionario)
    assert leer_cuestionario(cuestionario) == {"P-01": "Colombia, Chile, Perú y Ecuador."}


def test_historial_sqlite_guarda_versiones_y_respuestas(tmp_path):
    from generador_rfd.almacen import Almacen

    a = Almacen(tmp_path / "rfd.db")
    r = publicar(_demo_con_preguntas(), tmp_path / "RFD.docx")
    base = a.registrar(r.datos, origen="generado", ruta_docx=r.salida, calidad={"puntaje": 0.9})
    assert a.responder(base, "P-01", "Colombia y Chile")["estado"] == "respondida"
    assert a.responder(base, "P-02", "Pendiente")["estado"] == "pendiente"
    assert a.respuestas(base) == {"P-01": "Colombia y Chile"}
    hijo = a.registrar({**r.datos, "version": "0.2", "preguntas_cliente": []}, origen="mejorado",
                       ruta_docx=tmp_path / "RFD_v0.2.docx", padre_id=base)
    filas = {f["id"]: f for f in a.listar()}
    assert filas[base]["mejorado"] and filas[base]["respondidas"] == 1 and filas[base]["calidad"] == 0.9
    assert filas[hijo]["padre_id"] == base and filas[hijo]["version"] == "0.2"
    # Un RFD anterior (sin preguntas ni versión) sigue siendo una base válida.
    viejo = json.loads((EJEMPLOS / "rfd_demo.json").read_text(encoding="utf-8"))
    (tmp_path / "salidas").mkdir()
    publicar(viejo, tmp_path / "salidas" / "RFD_VIEJO.docx")
    assert a.importar_salidas(tmp_path / "salidas") == 1


def test_mejora_sube_version_y_detecta_respuestas_sin_incorporar(tmp_path, monkeypatch):
    from generador_rfd import pipeline

    def adaptar_falso(*, datos, respuestas, adjuntos, **_):
        nuevo = json.loads(json.dumps({k: v for k, v in datos.items() if k not in ("version", "historial")}))
        nuevo["alcance"]["introduccion"] = ["El alcance comprende Colombia y Chile."]
        nuevo["preguntas_cliente"] = [p for p in nuevo["preguntas_cliente"] if p["id"] != "P-01"]
        nuevo["cambios"] = [{"pregunta": "P-01", "seccion": "1.3 Alcance", "cambio": "Se fijan los países."}]
        return nuevo

    monkeypatch.setattr(pipeline, "adaptar_rfd", adaptar_falso)
    monkeypatch.setattr(pipeline, "asegurar_calidad", lambda d, *a, **k: (d, {"puntaje": 1.0, "umbral": 0.85, "criterios": [], "rondas": 0}))
    base = pipeline.normalizar(_demo_con_preguntas())
    r = pipeline.mejorar(pipeline.OpcionesMejora(
        base=tmp_path / "RFD_DEMO.docx", salida_dir=tmp_path, respuestas={"P-01": "Colombia y Chile", "P-02": "Sí, coexistirán"},
        datos_base=base, revisar_word=False))
    assert r.salida.name == "RFD_DEMO_v0.2.docx"
    assert r.datos["version"] == "0.2" and r.datos["historial"][-1]["version"] == "0.2"
    assert [p["id"] for p in r.datos["preguntas_cliente"]] == ["P-02"]
    assert any(h.codigo == "respuesta_sin_incorporar" and "P-02" in h.mensaje for h in r.hallazgos)
    assert "0.2" in texto_docx(r.salida)


def test_reglas_del_equipo_se_inyectan_y_verifican(tmp_path, monkeypatch):
    from generador_rfd import pipeline
    from generador_rfd.almacen import Almacen
    from generador_rfd.calidad import evaluar
    from generador_rfd.modelo import prompt_adaptacion
    from generador_rfd.reglas import Regla, bloque_prompt, incumplidas

    a = Almacen(tmp_path / "rfd.db")
    evitar = a.guardar_regla(Regla(texto="No usar enumeraciones abiertas como etc.", patron="etc.|entre otros"))
    exigir = a.guardar_regla(Regla(texto="Cada RF incluye un criterio de timeout", tipo="exigir", seccion="criterios", patron="timeout"))
    otro = a.guardar_regla(Regla(texto="Sólo para otro cliente: no citar SAP", cliente="Otro SA", patron="SAP"))
    a.guardar_regla(Regla(texto="Regla desactivada de prueba", activa=False))
    with pytest.raises(ValueError, match="expresión válida"):
        a.guardar_regla(Regla(texto="Patrón roto en la verificación", patron="re:(abc"))
    reglas = [r for r in a.reglas_para("Cliente Demostración") if not r.predeterminada]
    assert [r.id for r in reglas] == [evitar.id, exigir.id]
    assert otro.id in [r.id for r in a.reglas_para("otro sa")]

    datos = pipeline.normalizar(_demo_con_preguntas())
    rf = datos["requerimientos"][0]
    rf["criterios_aceptacion"][0] += " Aplica a solicitudes, reclamos, etc."
    fallas = dict((r.id, d) for r, d in incumplidas(datos, reglas))
    assert "etc." in fallas[evitar.id] and rf["id"] in fallas[evitar.id]
    assert fallas[exigir.id].startswith("falta en") and rf["id"] in fallas[exigir.id]
    ev = {c.id: c for c in evaluar(datos, None, False, reglas).criterios}
    assert not ev[f"regla.R{evitar.id}"].ok and not ev[f"regla.R{exigir.id}"].ok

    bloque = bloque_prompt(reglas)
    assert f"[R{evitar.id}] NO HACER (Todo el documento)" in bloque and f"[R{exigir.id}] HACER SIEMPRE (Criterios" in bloque
    prompt = crear_prompt(cargar_fuentes([EJEMPLOS / "transcripcion_demo.txt"], []), "", "C", "C-1", "nuevo", "x", None, None, bloque)
    assert prompt.index("REGLAS DE INTEGRIDAD") < prompt.index("REGLAS DEL EQUIPO") < prompt.index("CÓMO REDACTAR")
    assert "REGLAS DEL EQUIPO" in prompt_adaptacion(datos, [], [], bloque)

    recibido = {}

    def adaptar_falso(*, datos, reglas="", **_):
        recibido["reglas"] = reglas
        nuevo = json.loads(json.dumps({k: v for k, v in datos.items() if k not in ("version", "historial")}))
        nuevo["cambios"] = [{"pregunta": "P-01", "seccion": "1.3 Alcance", "cambio": "Se fijan los países."}]
        return nuevo

    monkeypatch.setattr(pipeline, "adaptar_rfd", adaptar_falso)
    monkeypatch.setattr(pipeline, "asegurar_calidad", lambda d, *a, **k: (d, {"puntaje": 1.0, "umbral": 0.85, "criterios": [], "rondas": 0}))
    r = pipeline.mejorar(pipeline.OpcionesMejora(base=tmp_path / "RFD_DEMO.docx", salida_dir=tmp_path, respuestas={"P-01": "Chile"},
                                                 datos_base=datos, revisar_word=False, reglas=reglas))
    assert "REGLAS DEL EQUIPO" in recibido["reglas"]
    assert {h.codigo for h in r.hallazgos} >= {"regla_incumplida"}


def test_reglas_predeterminadas_del_documento_de_correcciones(tmp_path):
    from generador_rfd.almacen import Almacen
    from generador_rfd.reglas import bloque_prompt, incumplidas

    a = Almacen(tmp_path / "rfd.db")
    defecto = [r for r in a.reglas() if r.predeterminada]
    assert [r.codigo for r in defecto] == [f"REG-{i:03}" for i in range(1, 31)]
    reg003 = next(r for r in defecto if r.codigo == "REG-003")
    reg003.activa, reg003.texto = False, "Texto ajustado por el equipo"
    a.guardar_regla(reg003)
    assert Almacen(tmp_path / "rfd.db").cargar_reglas_predeterminadas() == 0  # no duplica ni reactiva
    assert not next(r for r in a.reglas() if r.codigo == "REG-003").activa
    with pytest.raises(ValueError, match="desactívela"):
        a.eliminar_regla(reg003.id)
    restaurada = a.restaurar_regla(reg003.id)
    assert restaurada.activa and restaurada.texto.startswith("Excluir condiciones de revisión humana")

    reglas = a.reglas_para("Banco Northwind")
    bloque = bloque_prompt(reglas)
    assert "Narrativas internas y autoconfirmaciones:" in bloque and "[REG-030]" in bloque
    assert "CONDICIONES DE APLICACIÓN" in bloque and "token de autenticación" in bloque

    datos = normalizar(_demo_con_preguntas())
    datos["justificacion"] = [
        "La documentación recibida describe el portal de clientes. El resultado inmediato solicitado es un RFD para revisión humana "
        "y la fuente no autoriza iniciar directamente la implementación.",
        "La adecuación deberá considerar la autenticación personalizada mediante tokens del sistema existente.",
    ]
    datos["proceso_actual"] = ["La transcripción identifica dos interfaces. No se suministra el inventario del portal administrativo."]
    datos["anexos"] = [{"id": "F-01", "nombre": "writing-block.pdf", "uso": "Contexto; base de RF-01."},
                       {"id": "F-02", "nombre": "Repositorios del proyecto (CodeGraph)", "uso": "Inventario parcial; sustento AS-IS de RF-01."}]
    fallas = {r.codigo for r, _ in incumplidas(datos, reglas)}
    assert {"REG-003", "REG-006", "REG-024", "REG-026", "REG-027", "REG-028"} <= fallas
    assert "REG-001" not in fallas  # V-02: los tokens de autenticación del sistema no son tokens de IA

    con_anexos = publicar(datos, tmp_path / "con_anexos.docx")
    assert "Capítulo 8" in texto_docx(con_anexos.salida)
    datos["anexos"] = []
    sin_anexos = publicar(datos, tmp_path / "sin_anexos.docx")
    assert "Capítulo 8" not in texto_docx(sin_anexos.salida) and "Capítulo 7" in texto_docx(sin_anexos.salida)


def test_adaptadores_agy_grok_opencode(tmp_path, monkeypatch):
    import subprocess as sp

    from generador_rfd import motores
    from generador_rfd.modelo import Uso, invocar

    llamadas: list[dict] = []
    salidas = {
        "agy": "\n".join([
            '{"event":"init","init":{"model":"gemini-3.8-flash-low"}}',
            '{"event":"result","result":{"status":"SUCCESS","response":"","structured_output":{"ok":true},'
            '"usage":{"input_tokens":120,"output_tokens":8,"thinking_tokens":2}}}',
        ]),
        "grok": '{"structured_output":{"ok":true},"usage":{"input_tokens":50,"output_tokens":4},"total_cost_usd":0.01}',
        "opencode": "\n".join([
            '{"type":"step_start","part":{}}',
            '{"type":"text","part":{"type":"text","text":"```json\\n{\\"ok\\": "}}',
            '{"type":"text","part":{"type":"text","text":"true}\\n```"}}',
            '{"type":"step_finish","part":{"tokens":{"input":30,"output":5,"reasoning":1,"cache":{"read":10}},"cost":0}}',
        ]),
    }

    def correr_falso(comando, *, entrada=None, tiempo, cwd=None, env=None):
        cli = Path(comando[0]).name
        llamadas.append({"cli": cli, "comando": comando, "entrada": entrada, "env": env or {},
                         "prompt_file": Path(comando[comando.index("--prompt-file") + 1]).read_text(encoding="utf-8")
                         if "--prompt-file" in comando else None})
        return sp.CompletedProcess(comando, 0, salidas[cli], "")

    monkeypatch.setattr(motores, "ejecutable", lambda cli: cli)
    monkeypatch.setattr(motores, "_correr", correr_falso)
    esquema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    uso = Uso()
    for cli, modelo, esfuerzo in [("agy", "gemini-3.8-flash-low", "high"), ("grok", "grok-4.7", "low"), ("opencode", "opencode/big-pickle", "high")]:
        assert invocar(proveedor=cli, modelo=modelo, prompt="PROMPT-RFD", esquema=esquema, directorio=tmp_path,
                       uso=uso, esfuerzo=esfuerzo) == {"ok": True}
    agy, grok, opencode = llamadas
    # agy: -p no lee stdin; el prompt va como NDJSON por stream-json, con el esquema en un archivo.
    assert agy["comando"][-1] == "-p=" and "--sandbox" in agy["comando"] and "--disable-slash-commands" in agy["comando"]
    assert agy["comando"][agy["comando"].index("--input-format") + 1] == "stream-json"
    assert agy["comando"][agy["comando"].index("--effort") + 1] == "high"
    mensaje = json.loads(agy["entrada"])
    assert mensaje["event"] == "user" and mensaje["message"]["role"] == "user" and "PROMPT-RFD" in mensaje["message"]["content"]
    # grok: prompt por archivo, system prompt propio y sin subagentes ni web.
    assert grok["prompt_file"] == "PROMPT-RFD"
    for opcion in ("--system-prompt-override", "--no-subagents", "--disable-web-search", "--json-schema"):
        assert opcion in grok["comando"]
    # opencode: sin --json-schema, el esquema va en el prompt; se desactivan CLAUDE.md y la config del proyecto.
    assert "--pure" in opencode["comando"] and opencode["comando"][opencode["comando"].index("--variant") + 1] == "high"
    assert "FORMATO DE RESPUESTA" in opencode["entrada"] and '"required": ["ok"]' in opencode["entrada"]
    assert opencode["env"]["OPENCODE_DISABLE_CLAUDE_CODE"] == "1" and opencode["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert uso.llamadas == 3 and uso.tokens_entrada == 120 + 50 + 40 and uso.costo_usd == pytest.approx(0.01)
    with pytest.raises(ValueError, match="CLI no admitida"):
        invocar(proveedor="ollama", modelo="x", prompt="p", esquema=esquema, directorio=tmp_path)


def test_catalogos_de_modelos_por_cli(monkeypatch):
    import subprocess as sp

    from generador_rfd import motores

    textos = {
        "agy": ("Fetching available models...\ngemini-3.8-flash-high\tGemini 3.8 Flash (High)\nclaude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n", ""),
        "grok": ("You are not authenticated.\n\nDefault model: grok-4.7\n\nAvailable models:\n  * grok-4.7 (default)\n", ""),
        "opencode": ('opencode/big-pickle\n{"name": "Big Pickle", "limit": {"context": 200000}, "cost": {"input": 0, "output": 0}, "variants": {}}\n'
                     'opencode/exo-free\n{"name": "Exo Free", "limit": {"context": 1048576}, "variants": {"high": {"reasoningEffort": "high"}}}\n', ""),
    }
    monkeypatch.setattr(motores, "ejecutable", lambda cli: cli)
    monkeypatch.setattr(motores, "_correr", lambda comando, **_: sp.CompletedProcess(comando, 0, *textos[Path(comando[0]).name]))
    agy = motores.catalogo("agy")
    assert agy["disponible"] and [m["id"] for m in agy["modelos"]] == ["gemini-3.8-flash-high", "claude-sonnet-4-6"]
    grok = motores.catalogo("grok")
    assert not grok["disponible"] and "grok login" in grok["detalle"]
    oc = motores.catalogo("opencode")
    assert [(m["id"], m["nombre"], m["niveles"]) for m in oc["modelos"]] == [
        ("opencode/big-pickle", "Big Pickle", []), ("opencode/exo-free", "Exo Free", ["high"])]
    assert "200k de contexto" in oc["modelos"][0]["detalle"]
    monkeypatch.setattr(motores, "ejecutable", lambda cli: None)
    assert "no está instalado" in motores.catalogo("grok")["detalle"]


requiere_codex = pytest.mark.skipif(not shutil.which("codex"), reason="Codex CLI no está en PATH")


@pytest.mark.codex
@requiere_codex
def test_codex_analiza_un_documento(tmp_path):
    from generador_rfd.modelo import Uso

    uso = Uso()
    fuentes = cargar_fuentes([], [EJEMPLOS / "contexto_demo.docx"])
    analisis = analizar_fuentes(fuentes, cliente="Cliente prueba", proveedor="codex",
                                modelo=os.environ.get("RFD_MODELO_CODEX", "gpt-6-luna"), esfuerzo="low",
                                directorio=tmp_path, uso=uso)
    assert analisis["F01"]["resumen"]
    assert uso.llamadas == 1 and uso.tokens_entrada > 0
    assert not list(tmp_path.iterdir()), "el directorio temporal de Codex debe eliminarse"


@pytest.mark.claude
@requiere_claude
def test_cli_devuelve_salida_estructurada(tmp_path):
    esquema = {
        "type": "object",
        "properties": {"estado": {"type": "string", "enum": ["ok"]}, "suma": {"type": "integer"}},
        "required": ["estado", "suma"],
        "additionalProperties": False,
    }
    p = subprocess.run(
        comando_claude(CLAUDE, MODELO, esquema),
        input="Responde estado=ok y suma=2+3.", text=True, encoding="utf-8",
        capture_output=True, timeout=180, cwd=tmp_path, check=False,
    )
    assert p.returncode == 0, p.stderr[-800:]
    respuesta = json.loads(p.stdout[p.stdout.find("{"):])
    assert respuesta["is_error"] is False, respuesta.get("result")
    assert respuesta["structured_output"] == {"estado": "ok", "suma": 5}
    uso = respuesta["usage"]
    assert uso["input_tokens"] + uso["cache_creation_input_tokens"] + uso["cache_read_input_tokens"] < 30_000


@pytest.mark.claude
@requiere_claude
def test_analisis_por_documento(tmp_path):
    fuentes = cargar_fuentes([], [EJEMPLOS / "contexto_demo.docx"])
    analisis = analizar_fuentes(fuentes, cliente="Cliente prueba", proveedor="claude", modelo=MODELO, directorio=tmp_path)
    a = analisis["F01"]
    assert a["resumen"] and a["terminos_codigo"]
    assert all(e.startswith("F01") for e in a["evidencias"])
    assert not list(tmp_path.iterdir()), "el directorio temporal de Claude debe eliminarse"


@pytest.mark.claude
@requiere_claude
def test_api_genera_word_con_varios_archivos(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(servidor, "SALIDAS", tmp_path)
    cliente = TestClient(servidor.app)
    archivos = [
        ("transcripciones", ("transcripcion_demo.txt", (EJEMPLOS / "transcripcion_demo.txt").read_bytes())),
        ("contextos", ("contexto_demo.docx", (EJEMPLOS / "contexto_demo.docx").read_bytes())),
        ("contextos", ("presentacion_demo.pptx", (EJEMPLOS / "presentacion_demo.pptx").read_bytes())),
    ]
    r = cliente.post("/api/generar", files=archivos, data={
        "cliente": "Cliente prueba", "codigo": "TEST-API", "tipo_proyecto": "existente",
        "proveedor": "claude", "modelo": MODELO, "revisar_word": "false",
    })
    assert r.status_code == 200, r.text
    id_ = r.json()["id"]
    limite = time.time() + 1200
    while (t := cliente.get(f"/api/trabajos/{id_}").json())["estado"] == "en_curso":
        assert time.time() < limite, "la generación superó 20 minutos"
        time.sleep(3)
    assert t["estado"] == "listo", t.get("error")
    assert [f["nombre"] for f in t["fuentes"]] == ["transcripcion_demo.txt", "contexto_demo.docx", "presentacion_demo.pptx"]
    assert t["uso"]["llamadas"] == 4, "tres análisis y una redacción"
    word = cliente.get(f"/api/trabajos/{id_}/archivo/docx")
    assert word.status_code == 200 and word.content[:2] == b"PK"
    assert cliente.get(f"/api/trabajos/{id_}/archivo/analisis").status_code == 200
    assert (tmp_path / "RFD_TEST-API.revision.md").is_file()


def test_excel_con_dimension_falsa_se_lee_completo(tmp_path):
    import re
    import zipfile

    from openpyxl import Workbook

    libro = Workbook()
    for i in range(5):
        libro.active.append([f"a{i}", f"b{i}"])
    base = tmp_path / "base.xlsx"
    libro.save(base)
    ruta = tmp_path / "dim_a1.xlsx"
    with zipfile.ZipFile(base) as origen, zipfile.ZipFile(ruta, "w") as destino:
        for n in origen.namelist():
            datos = origen.read(n)
            if n == "xl/worksheets/sheet1.xml":
                datos = re.sub(rb'<dimension ref="[^"]*"', b'<dimension ref="A1"', datos)
            destino.writestr(n, datos)
    assert "H1F5: a4 | b4" in leer_documento(ruta)
