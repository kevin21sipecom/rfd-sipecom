import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PreguntaGuardada, type RfdDetalle, type RfdResumen, type Trabajo } from "./api";
import { Campo, Icono, Segmentado, ZonaArchivos } from "./components";
import type { Motor } from "./Motor";
import { PASOS_CONTINUAR, PASOS_IMPORTAR, PASOS_MEJORA, Progreso, ResultadoVista } from "./Panel";
import { PanelPrototipo } from "./Prototipo";

const EXTENSIONES = [".txt", ".md", ".docx", ".pptx", ".pdf", ".xlsx"];

const ORIGEN: Record<string, string> = { generado: "generado", mejorado: "mejorado", importado: "importado", en_avance: "en avance", continuado: "continuado" };

function pasosDe(t: Trabajo) {
  if (t.tipo === "preguntas") return undefined;
  return t.tipo === "continuacion" ? PASOS_CONTINUAR : t.tipo === "importacion" ? PASOS_IMPORTAR : PASOS_MEJORA;
}

function siguiente(version: string): string {
  const [a, b] = version.split(".").map(Number);
  return Number.isFinite(a) && Number.isFinite(b) ? `${a}.${b + 1}` : "0.2";
}

function Pregunta({ rfdId, p, onGuardada }: { rfdId: number; p: PreguntaGuardada; onGuardada: (p: PreguntaGuardada) => void }) {
  const [texto, setTexto] = useState(p.respuesta);
  const [estado, setEstado] = useState<"" | "guardando" | "guardado" | "error">("");
  const original = useRef(p.respuesta);
  useEffect(() => { setTexto(p.respuesta); original.current = p.respuesta; }, [p.respuesta]);

  const guardar = async () => {
    if (texto === original.current) return;
    setEstado("guardando");
    try {
      const r = await api.responder(rfdId, p.pid, texto);
      original.current = r.respuesta;
      onGuardada({ ...p, respuesta: r.respuesta, estado: r.estado });
      setEstado("guardado");
      setTimeout(() => setEstado(""), 1500);
    } catch { setEstado("error"); }
  };

  return (
    <li className={`pregunta-item ${p.estado}`}>
      <div className="pregunta-cab">
        <span className="rf-id">{p.pid}</span>
        <strong>{p.tema}</strong>
        <span className={`chip-estado ${p.estado}`}>{{ abierta: "Abierta", respondida: "Respondida", pendiente: "Pendiente" }[p.estado]}</span>
        {p.relacion.length > 0 && <span className="relacion">{p.relacion.join(" · ")}</span>}
      </div>
      <p className="pregunta-contexto">{p.contexto}</p>
      <p className="pregunta-texto">{p.pregunta}</p>
      <textarea value={texto} onChange={(e) => setTexto(e.target.value)} onBlur={guardar} rows={2}
        placeholder="Respuesta del cliente (se guarda al salir del campo). Escriba «Pendiente» si aún no está definida." />
      {estado && <span className={`guardado ${estado}`}>{{ guardando: "Guardando…", guardado: "Guardado", error: "No se guardó" }[estado]}</span>}
    </li>
  );
}

export function Historial({ motor, wordDisponible, seleccionInicial }: {
  motor: Motor; wordDisponible: boolean; seleccionInicial: number | null;
}) {
  const [lista, setLista] = useState<RfdResumen[]>([]);
  const [seleccion, setSeleccion] = useState<number | null>(seleccionInicial);
  const [detalle, setDetalle] = useState<RfdDetalle | null>(null);
  const [adjuntos, setAdjuntos] = useState<File[]>([]);
  const [modo, setModo] = useState<"mejorar" | "continuar" | "prototipo">("mejorar");
  const [contexto, setContexto] = useState<File[]>([]);
  const [instruccion, setInstruccion] = useState("");
  const [importando, setImportando] = useState(false);
  const [archivoAvance, setArchivoAvance] = useState<File | null>(null);
  const [clienteAvance, setClienteAvance] = useState("");
  const [codigoAvance, setCodigoAvance] = useState("");
  const [tituloAvance, setTituloAvance] = useState("");
  const [revisarWord, setRevisarWord] = useState(true);
  const [trabajo, setTrabajo] = useState<Trabajo | null>(null);
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");
  const [filtro, setFiltro] = useState("");
  const entradaCuestionario = useRef<HTMLInputElement>(null);

  const recargarLista = useCallback(() => api.rfds().then(setLista).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { recargarLista(); }, [recargarLista]);
  useEffect(() => { if (seleccionInicial) setSeleccion(seleccionInicial); }, [seleccionInicial]);
  useEffect(() => {
    if (seleccion == null) { setDetalle(null); return; }
    setDetalle(null);
    // Una importación en curso sigue visible aunque se cambie de RFD en la lista.
    setTrabajo((t) => (t?.tipo === "importacion" && t.estado === "en_curso" ? t : null));
    setAdjuntos([]);
    setContexto([]);
    setInstruccion("");
    setAviso("");
    api.rfd(seleccion).then((d) => {
      setDetalle(d);
      // Quien está prototipando sigue en esa pestaña al cambiar de RFD.
      setModo((m) => (m === "prototipo" ? m : d.origen === "en_avance" || d.origen === "continuado" ? "continuar" : "mejorar"));
    }).catch((e: Error) => setError(e.message));
  }, [seleccion]);
  useEffect(() => {
    if (seleccion == null && lista.length) setSeleccion(lista.find((r) => !r.mejorado)?.id ?? lista[0].id);
  }, [lista, seleccion]);

  useEffect(() => {
    if (!trabajo || trabajo.estado !== "en_curso") return;
    const t = setInterval(() => api.trabajo(trabajo.id).then((x) => {
      setTrabajo(x);
      if (x.estado === "listo") recargarLista();
      if (x.estado === "listo" && x.tipo === "importacion" && x.resultado?.rfd_id) {
        // El proyecto importado se abre en el historial, listo para continuarlo.
        setImportando(false);
        setArchivoAvance(null);
        setSeleccion(x.resultado.rfd_id);
      }
    }).catch((e: Error) => setError(e.message)), 1500);
    return () => clearInterval(t);
  }, [trabajo, recargarLista]);

  const actualizarPregunta = (p: PreguntaGuardada) => {
    setDetalle((d) => d && { ...d, preguntas: d.preguntas.map((x) => (x.pid === p.pid ? p : x)) });
    recargarLista();
  };

  const cargarCuestionario = async (archivo: File | undefined) => {
    if (!archivo || !detalle) return;
    setError("");
    try {
      const r = await api.cargarCuestionario(detalle.id, archivo);
      setDetalle({ ...detalle, preguntas: r.preguntas });
      setAviso(`Cuestionario leído: ${r.guardadas} respuesta(s) guardada(s).`);
      recargarLista();
    } catch (e) { setError((e as Error).message); }
  };

  const lanzar = async (tipo: "mejora" | "preguntas" | "continuar") => {
    if (!detalle) return;
    setError("");
    const f = new FormData();
    motor.agregar(f);
    if (tipo === "mejora") {
      adjuntos.forEach((a) => f.append("adjuntos", a));
      f.append("revisar_word", String(revisarWord && wordDisponible));
    }
    if (tipo === "continuar") {
      contexto.forEach((a) => f.append("adjuntos", a));
      f.append("instruccion", instruccion.trim());
      f.append("revisar_word", String(revisarWord && wordDisponible));
    }
    try {
      const { id } = tipo === "mejora" ? await api.mejorar(detalle.id, f)
        : tipo === "continuar" ? await api.continuar(detalle.id, f) : await api.crearPreguntas(detalle.id, f);
      setTrabajo(await api.trabajo(id));
    } catch (e) { setError((e as Error).message); }
  };

  const importar = async () => {
    if (!archivoAvance) return;
    setError("");
    const f = new FormData();
    motor.agregar(f);
    f.append("archivo", archivoAvance);
    f.append("cliente", clienteAvance.trim());
    f.append("codigo", codigoAvance.trim());
    f.append("titulo", tituloAvance.trim());
    try {
      const { id } = await api.importar(f);
      setTrabajo(await api.trabajo(id));
    } catch (e) { setError((e as Error).message); }
  };

  const respondidas = detalle?.preguntas.filter((p) => p.estado === "respondida").length ?? 0;
  const total = detalle?.preguntas.length ?? 0;
  const ocupado = trabajo?.estado === "en_curso";
  const interruptorWord = wordDisponible && (
    <label className="interruptor">
      <input type="checkbox" checked={revisarWord} onChange={(e) => setRevisarWord(e.target.checked)} />
      <span className="pista" />
      <span>Revisar con Microsoft Word<small>Índice con páginas y PDF de la nueva versión.</small></span>
    </label>
  );
  const faltaAvance = !archivoAvance || !clienteAvance.trim() || !codigoAvance.trim();
  const grupos = lista
    .filter((r) => !filtro || `${r.codigo} ${r.cliente} ${r.titulo}`.toLowerCase().includes(filtro.toLowerCase()))
    .reduce<Record<string, RfdResumen[]>>((g, r) => ({ ...g, [r.codigo]: [...(g[r.codigo] ?? []), r] }), {});

  return (
    <main className="contenido historial">
      <aside className="lista-rfds">
        <div className="lista-cab">
          <h2>RFD guardados</h2>
          <span>{lista.length}</span>
        </div>
        <button type="button" className="boton ancho" disabled={ocupado} onClick={() => { setImportando(true); setTrabajo(null); }}>
          <Icono n="upload" size={15} /> Importar proyecto en avance
        </button>
        <div className="entrada-icono buscador">
          <Icono n="eye" size={14} />
          <input value={filtro} onChange={(e) => setFiltro(e.target.value)} placeholder="Buscar por código, cliente o título" />
        </div>
        {Object.entries(grupos).map(([codigo, versiones]) => (
          <div key={codigo} className="grupo-rfd">
            <div className="grupo-cab"><b>{codigo}</b><span>{versiones[0].cliente}</span></div>
            {versiones.map((r) => (
              <button key={r.id} type="button" className={`item-rfd ${seleccion === r.id ? "activo" : ""}`} onClick={() => setSeleccion(r.id)}>
                <span className="version">v{r.version}</span>
                <span className="item-texto">
                  <span className="item-titulo">{r.titulo}</span>
                  <small>{r.archivo} · {new Date(r.creado).toLocaleDateString("es")} · {ORIGEN[r.origen] ?? r.origen}</small>
                </span>
                <span className="item-meta">
                  {r.calidad != null && <em className={r.calidad >= 0.85 ? "ok" : "atencion"}>{Math.round(r.calidad * 100)}%</em>}
                  {r.preguntas > 0 && <em>{r.respondidas}/{r.preguntas}</em>}
                  {r.origen === "en_avance" && !r.mejorado && <em className="atencion">en avance</em>}
                  {r.mejorado && <em className="tenue">{r.origen === "en_avance" ? "continuado" : "mejorado"}</em>}
                </span>
              </button>
            ))}
          </div>
        ))}
        {!lista.length && <p className="vacio">Aún no hay RFD. Genere uno en la pestaña «Generar» o importe uno en avance.</p>}
      </aside>

      <section className="detalle-rfd">
        {!detalle && <div className="panel"><p className="vacio">{seleccion ? "Cargando…" : "Seleccione un RFD."}</p></div>}
        {detalle && (
          <>
            <div className="panel cabecera-rfd">
              <div>
                <small>{detalle.codigo} · {detalle.cliente} · versión {detalle.version} · {ORIGEN[detalle.origen] ?? detalle.origen}{detalle.modelo ? ` con ${detalle.modelo}` : ""}</small>
                <h2>{detalle.titulo}</h2>
                <p>{detalle.objetivo}</p>
              </div>
              <div className="acciones-rfd">
                {detalle.archivos.docx && <a className="boton" href={api.archivoRfd(detalle.id, "docx")}><Icono n="download" size={15} /> Word</a>}
                {detalle.archivos.pdf && <button type="button" className="boton" onClick={() => api.abrirRfd(detalle.id, "pdf")}><Icono n="doc" size={15} /> PDF</button>}
                {detalle.archivos.cuestionario && <a className="boton" href={api.archivoRfd(detalle.id, "cuestionario")}><Icono n="download" size={15} /> Cuestionario</a>}
                {detalle.archivos.prototipo && <a className="boton" href={api.archivoRfd(detalle.id, "prototipo")} target="_blank" rel="noreferrer"><Icono n="eye" size={15} /> Prototipo</a>}
                <button type="button" className="boton fantasma" onClick={() => api.abrirRfd(detalle.id, "carpeta")}><Icono n="folder" size={15} /></button>
              </div>
              {detalle.cambios.length > 0 && (
                <details className="cambios-version">
                  <summary>{detalle.cambios.length} cambio(s) de la versión {detalle.version}</summary>
                  <ul>{detalle.cambios.map((c, i) => <li key={i}><b>{c.pregunta}</b> · {c.seccion}: {c.cambio}</li>)}</ul>
                </details>
              )}
            </div>

            <div className="panel">
              <div className="seccion-cab">
                <h3>Preguntas para el cliente</h3>
                {total > 0 && (
                  <div className="barra-avance" title={`${respondidas} de ${total} respondidas`}>
                    <span style={{ width: `${(respondidas / total) * 100}%` }} />
                    <small>{respondidas}/{total} respondidas</small>
                  </div>
                )}
              </div>
              {total === 0 ? (
                <div className="sin-preguntas">
                  <p>Este RFD se generó antes de la sección de preguntas. Puede redactarlas a partir de sus definiciones, pendientes y supuestos, sin modificar el resto del documento.</p>
                  <button type="button" className="boton" disabled={ocupado || !motor.listo} onClick={() => lanzar("preguntas")}>
                    <Icono n="spark" size={15} /> Generar preguntas con {motor.modelo || motor.proveedor}
                  </button>
                </div>
              ) : (
                <>
                  <div className="acciones-preguntas">
                    <button type="button" className="boton" onClick={() => entradaCuestionario.current?.click()}>
                      <Icono n="upload" size={15} /> Cargar cuestionario respondido
                    </button>
                    <input ref={entradaCuestionario} type="file" accept=".docx" hidden
                      onChange={(e) => { cargarCuestionario(e.target.files?.[0]); e.target.value = ""; }} />
                    <span className="campo-ayuda">o escriba las respuestas aquí; se guardan automáticamente en la base de datos.</span>
                  </div>
                  {aviso && <p className="aviso-ok">{aviso}</p>}
                  <ol className="lista-preguntas">
                    {detalle.preguntas.map((p) => <Pregunta key={p.pid} rfdId={detalle.id} p={p} onGuardada={actualizarPregunta} />)}
                  </ol>
                </>
              )}
            </div>
          </>
        )}
      </section>

      <aside className="columna-panel">
        <div className="panel">
          {trabajo?.estado === "listo" && trabajo.resultado ? (
            <ResultadoVista trabajo={trabajo} onNuevo={() => { setTrabajo(null); if (trabajo.resultado?.rfd_id) setSeleccion(trabajo.resultado.rfd_id); }}
              textoNuevo="Ver la nueva versión" />
          ) : importando ? (
            <>
              <h2 className="panel-titulo"><Icono n="upload" size={16} /> Importar proyecto en avance</h2>
              <p className="campo-ayuda">
                Cargue el Word de un RFD a medio redactar. Queda en el historial como «en avance», con su archivo original enlazado,
                para continuarlo después sin perder nada de lo ya escrito.
              </p>
              <ZonaArchivos titulo="RFD en avance" descripcion="Un archivo .docx" archivos={archivoAvance ? [archivoAvance] : []}
                aceptar={[".docx"]} onCambio={(a) => setArchivoAvance(a[a.length - 1] ?? null)} />
              <div className="rejilla-1">
                <Campo etiqueta="Cliente *"><input value={clienteAvance} onChange={(e) => setClienteAvance(e.target.value)} placeholder="Nombre del cliente" /></Campo>
                <Campo etiqueta="Código RFD *"><input value={codigoAvance} onChange={(e) => setCodigoAvance(e.target.value)} placeholder="RFD-001" /></Campo>
                <Campo etiqueta="Título" ayuda="Opcional; si se deja vacío se toma del documento."><input value={tituloAvance} onChange={(e) => setTituloAvance(e.target.value)} /></Campo>
              </div>
              {motor.vista}
              {trabajo && <Progreso trabajo={trabajo} conCodigo={false} conWord={false} pasos={pasosDe(trabajo)} />}
              <button type="button" className="boton primario grande" disabled={ocupado || faltaAvance || !motor.listo} onClick={importar}>
                {ocupado ? <><span className="girando claro" /> Importando…</> : <><Icono n="upload" size={18} /> Importar al historial</>}
              </button>
              {!ocupado && faltaAvance && <p className="falta">Indique el Word en avance, el cliente y el código.</p>}
              <button type="button" className="boton fantasma ancho" disabled={ocupado} onClick={() => { setImportando(false); setTrabajo(null); }}>Volver al historial</button>
            </>
          ) : (
            <>
              <Segmentado valor={modo} onCambio={setModo} opciones={[
                { valor: "continuar", etiqueta: "Continuar", detalle: "completar" },
                { valor: "mejorar", etiqueta: "Mejorar", detalle: "con respuestas" },
                { valor: "prototipo", etiqueta: "Prototipo", detalle: "UI" },
              ]} />
              {modo === "prototipo" ? (
                detalle ? <PanelPrototipo rfd={detalle} motor={motor} /> : <p className="vacio">Seleccione un RFD.</p>
              ) : modo === "continuar" ? (
                <>
                  <h2 className="panel-titulo"><Icono n="play" size={16} /> Continuar RFD</h2>
                  <p className="campo-ayuda">
                    La IA conserva lo ya escrito y sólo completa lo que falta: secciones vacías, marcadores y «por confirmar». No necesita
                    respuestas del cliente; crea la versión {detalle ? siguiente(detalle.version) : "siguiente"} y la anterior queda intacta.
                  </p>
                  <ZonaArchivos titulo="Contexto adicional" descripcion="Opcional · transcripciones, especificaciones, correos" archivos={contexto}
                    aceptar={EXTENSIONES} onCambio={setContexto} />
                  <Campo etiqueta="¿Qué falta o en qué enfocarte?" ayuda="Opcional. Ej.: «completa los criterios de RF-03 y el esfuerzo»." ancho>
                    <textarea value={instruccion} onChange={(e) => setInstruccion(e.target.value)} rows={3} />
                  </Campo>
                  {motor.vista}
                  {interruptorWord}
                  <ul className="lista-control">
                    <li className={contexto.length ? "ok" : ""}><Icono n="check" size={14} />{contexto.length} documento(s) de contexto</li>
                    <li className={instruccion.trim() ? "ok" : ""}><Icono n="check" size={14} />{instruccion.trim() ? "Con instrucción" : "Sin instrucción"}</li>
                  </ul>
                  {trabajo && <Progreso trabajo={trabajo} conCodigo={false} conWord={revisarWord && wordDisponible} pasos={pasosDe(trabajo)} />}
                  <button type="button" className="boton primario grande" disabled={!detalle || ocupado || !motor.listo} onClick={() => lanzar("continuar")}>
                    {ocupado ? <><span className="girando claro" /> Procesando…</> : <><Icono n="spark" size={18} /> Continuar a v{detalle ? siguiente(detalle.version) : ""}</>}
                  </button>
                </>
              ) : (
            <>
              <h2 className="panel-titulo"><Icono n="refresh" size={16} /> Mejorar RFD</h2>
              <p className="campo-ayuda">
                El RFD no se rehace: se adapta a las respuestas del cliente, se cierran las definiciones resueltas, se registra cada cambio
                y se crea la versión {detalle ? siguiente(detalle.version) : "siguiente"}.
              </p>
              <ZonaArchivos titulo="Documentos del cliente" descripcion="Opcional · actas, correos, aclaraciones" archivos={adjuntos}
                aceptar={EXTENSIONES} onCambio={setAdjuntos} />
              {motor.vista}
              {interruptorWord}
              <ul className="lista-control">
                <li className={respondidas ? "ok" : ""}><Icono n="check" size={14} />{respondidas} respuesta(s) guardada(s)</li>
                <li className={adjuntos.length ? "ok" : ""}><Icono n="check" size={14} />{adjuntos.length} documento(s) del cliente</li>
              </ul>
              {trabajo && <Progreso trabajo={trabajo} conCodigo={false} conWord={revisarWord && wordDisponible} pasos={pasosDe(trabajo)} />}
              <button type="button" className="boton primario grande" disabled={!detalle || ocupado || (!respondidas && !adjuntos.length) || !motor.listo}
                onClick={() => lanzar("mejora")}>
                {ocupado ? <><span className="girando claro" /> Procesando…</> : <><Icono n="spark" size={18} /> Mejorar a v{detalle ? siguiente(detalle.version) : ""}</>}
              </button>
              {!ocupado && detalle && !respondidas && !adjuntos.length && <p className="falta">Responda al menos una pregunta o adjunte un documento del cliente.</p>}
              {detalle && lista.find((r) => r.id === detalle.id)?.mejorado && (
                <p className="campo-ayuda">Este RFD ya tiene una versión posterior; mejorar desde aquí crea otra rama.</p>
              )}
            </>
              )}
            </>
          )}
          {error && <div className="banda-error"><Icono n="alert" size={16} /><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="Cerrar"><Icono n="x" size={14} /></button></div>}
        </div>
      </aside>
    </main>
  );
}
