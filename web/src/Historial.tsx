import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PreguntaGuardada, type RfdDetalle, type RfdResumen, type Trabajo } from "./api";
import { Icono, ZonaArchivos } from "./components";
import { EnviarEstimador } from "./Estimador";
import type { Motor } from "./Motor";
import { PASOS_MEJORA, Progreso, ResultadoVista } from "./Panel";

const EXTENSIONES = [".txt", ".md", ".docx", ".pptx", ".pdf", ".xlsx"];

interface Proyecto {
  clave: string;
  codigo: string;
  cliente: string;
  principal: RfdResumen;          // versión más reciente: la que se muestra y se mejora
  registros: RfdResumen[];        // versiones e intentos, del más reciente al más antiguo
}

const numeroVersion = (v: string) => v.split(".").map(Number).reduce((a, n) => a * 1000 + (Number.isFinite(n) ? n : 0), 0);

/** Un proyecto por código RFD: la versión más alta y, a igualdad, el intento más reciente. */
function agrupar(lista: RfdResumen[]): Proyecto[] {
  const mapa = new Map<string, RfdResumen[]>();
  for (const r of lista) {
    const clave = r.codigo.trim().toLowerCase();
    mapa.set(clave, [...(mapa.get(clave) ?? []), r]);
  }
  return [...mapa.entries()].map(([clave, registros]) => {
    const orden = [...registros].sort((a, b) => numeroVersion(b.version) - numeroVersion(a.version) || b.creado.localeCompare(a.creado));
    return { clave, codigo: orden[0].codigo, cliente: orden[0].cliente, principal: orden[0], registros: orden };
  }).sort((a, b) => b.principal.creado.localeCompare(a.principal.creado));
}

/** Etiqueta de cada registro: «v0.2», y «v0.1 · intento 2» cuando la misma versión se generó varias veces. */
function etiquetas(registros: RfdResumen[]): Map<number, string> {
  const porVersion = new Map<string, RfdResumen[]>();
  for (const r of registros) porVersion.set(r.version, [...(porVersion.get(r.version) ?? []), r]);
  const salida = new Map<number, string>();
  for (const [version, rs] of porVersion) {
    const cronologico = [...rs].sort((a, b) => a.creado.localeCompare(b.creado));
    cronologico.forEach((r, i) => salida.set(r.id, cronologico.length > 1 ? `v${version} · intento ${i + 1}` : `v${version}`));
  }
  return salida;
}

const fecha = (iso: string) => new Date(iso).toLocaleDateString("es", { day: "2-digit", month: "short" });

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
    setTrabajo(null);
    setAdjuntos([]);
    setAviso("");
    api.rfd(seleccion).then(setDetalle).catch((e: Error) => setError(e.message));
  }, [seleccion]);
  useEffect(() => {
    if (seleccion == null && lista.length) setSeleccion(agrupar(lista)[0].principal.id);
  }, [lista, seleccion]);

  useEffect(() => {
    if (!trabajo || trabajo.estado !== "en_curso") return;
    const t = setInterval(() => api.trabajo(trabajo.id).then((x) => {
      setTrabajo(x);
      if (x.estado === "listo") recargarLista();
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

  const lanzar = async (tipo: "mejora" | "preguntas") => {
    if (!detalle) return;
    setError("");
    const f = new FormData();
    motor.agregar(f);
    if (tipo === "mejora") {
      adjuntos.forEach((a) => f.append("adjuntos", a));
      f.append("revisar_word", String(revisarWord && wordDisponible));
    }
    try {
      const { id } = tipo === "mejora" ? await api.mejorar(detalle.id, f) : await api.crearPreguntas(detalle.id, f);
      setTrabajo(await api.trabajo(id));
    } catch (e) { setError((e as Error).message); }
  };

  const respondidas = detalle?.preguntas.filter((p) => p.estado === "respondida").length ?? 0;
  const total = detalle?.preguntas.length ?? 0;
  const ocupado = trabajo?.estado === "en_curso";
  const proyectos = agrupar(lista);
  const visibles = proyectos.filter((p) => !filtro || `${p.codigo} ${p.cliente} ${p.principal.titulo}`.toLowerCase().includes(filtro.toLowerCase()));
  const proyecto = proyectos.find((p) => p.registros.some((r) => r.id === seleccion));
  const nombres = proyecto ? etiquetas(proyecto.registros) : new Map<number, string>();

  const eliminarIntento = async (r: RfdResumen) => {
    if (!window.confirm(`¿Quitar ${nombres.get(r.id) ?? "esta versión"} del historial? Los archivos en salidas/ no se borran.`)) return;
    try {
      await api.eliminarRfd(r.id);
      if (seleccion === r.id) setSeleccion(proyecto?.principal.id ?? null);
      recargarLista();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <main className="contenido historial">
      <aside className="lista-rfds">
        <div className="lista-cab">
          <h2>Proyectos</h2>
          <span>{proyectos.length} · {lista.length} versiones</span>
        </div>
        <div className="entrada-icono buscador">
          <Icono n="eye" size={14} />
          <input value={filtro} onChange={(e) => setFiltro(e.target.value)} placeholder="Buscar por código, cliente o título" />
        </div>
        <ul className="lista-proyectos">
          {visibles.map((p) => {
            const r = p.principal;
            const activo = proyecto?.clave === p.clave;
            const versiones = new Set(p.registros.map((x) => x.version)).size;
            const intentos = p.registros.length - versiones;
            return (
              <li key={p.clave}>
                <button type="button" className={`proyecto ${activo ? "activo" : ""}`} onClick={() => setSeleccion(r.id)}>
                  <span className="proyecto-cab">
                    <b>{p.codigo}</b>
                    <span className="version">v{r.version}</span>
                    {r.calidad != null && <em className={r.calidad >= 0.85 ? "ok" : "atencion"}>{Math.round(r.calidad * 100)}%</em>}
                  </span>
                  <span className="proyecto-titulo" title={r.titulo}>{r.titulo}</span>
                  <span className="proyecto-pie">
                    <span>{p.cliente}</span>
                    <span>{fecha(r.creado)}</span>
                  </span>
                  {(r.preguntas > 0 || p.registros.length > 1) && (
                    <span className="proyecto-pie">
                      {r.preguntas > 0 ? (
                        <span className="mini-avance" title={`${r.respondidas} de ${r.preguntas} preguntas respondidas`}>
                          <i style={{ width: `${(r.respondidas / r.preguntas) * 100}%` }} />
                        </span>
                      ) : <span />}
                      {p.registros.length > 1 && <small>{versiones} versión(es){intentos > 0 ? ` · ${intentos} intento(s)` : ""}</small>}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
        {!lista.length && <p className="vacio">Aún no hay RFD. Genere uno en la pestaña «Generar».</p>}
        {lista.length > 0 && !visibles.length && <p className="vacio">Ningún proyecto coincide con la búsqueda.</p>}
      </aside>

      <section className="detalle-rfd">
        {!detalle && <div className="panel"><p className="vacio">{seleccion ? "Cargando…" : "Seleccione un RFD."}</p></div>}
        {detalle && (
          <>
            <div className="panel cabecera-rfd">
              <div>
                <small>{detalle.codigo} · {detalle.cliente} · {nombres.get(detalle.id) ?? `v${detalle.version}`} · {detalle.origen}{detalle.modelo ? ` con ${detalle.modelo}` : ""}</small>
                <h2>{detalle.titulo}</h2>
                <p>{detalle.objetivo}</p>
              </div>
              <div className="acciones-rfd">
                {detalle.archivos.docx && <a className="boton" href={api.archivoRfd(detalle.id, "docx")}><Icono n="download" size={15} /> Word</a>}
                {detalle.archivos.pdf && <button type="button" className="boton" onClick={() => api.abrirRfd(detalle.id, "pdf")}><Icono n="doc" size={15} /> PDF</button>}
                {detalle.archivos.cuestionario && <a className="boton" href={api.archivoRfd(detalle.id, "cuestionario")}><Icono n="download" size={15} /> Cuestionario</a>}
                <button type="button" className="boton fantasma" onClick={() => api.abrirRfd(detalle.id, "carpeta")}><Icono n="folder" size={15} /></button>
              </div>
              {detalle.archivos.docx && <EnviarEstimador key={detalle.id} rfdId={detalle.id} codigo={detalle.codigo} version={detalle.version} />}
              {proyecto && proyecto.registros.length > 1 && (
                <div className="versiones" role="tablist" aria-label="Versiones del proyecto">
                  {proyecto.registros.map((r) => (
                    <span key={r.id} className={`version-chip ${r.id === detalle.id ? "activa" : ""}`}>
                      <button type="button" role="tab" aria-selected={r.id === detalle.id} onClick={() => setSeleccion(r.id)}
                        title={`${r.origen} · ${new Date(r.creado).toLocaleString("es")}${r.modelo ? ` · ${r.modelo}` : ""}`}>
                        {nombres.get(r.id)}{r.id === proyecto.principal.id && <em>actual</em>}
                      </button>
                      {r.id !== proyecto.principal.id && (
                        <button type="button" className="quitar" aria-label={`Quitar ${nombres.get(r.id)}`} onClick={() => eliminarIntento(r)}>
                          <Icono n="x" size={11} />
                        </button>
                      )}
                    </span>
                  ))}
                </div>
              )}
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
              {wordDisponible && (
                <label className="interruptor">
                  <input type="checkbox" checked={revisarWord} onChange={(e) => setRevisarWord(e.target.checked)} />
                  <span className="pista" />
                  <span>Revisar con Microsoft Word<small>Índice con páginas y PDF de la nueva versión.</small></span>
                </label>
              )}
              <ul className="lista-control">
                <li className={respondidas ? "ok" : ""}><Icono n="check" size={14} />{respondidas} respuesta(s) guardada(s)</li>
                <li className={adjuntos.length ? "ok" : ""}><Icono n="check" size={14} />{adjuntos.length} documento(s) del cliente</li>
              </ul>
              {trabajo && <Progreso trabajo={trabajo} conCodigo={false} conWord={revisarWord && wordDisponible}
                pasos={trabajo.tipo === "preguntas" ? undefined : PASOS_MEJORA} />}
              <button type="button" className="boton primario grande" disabled={!detalle || ocupado || (!respondidas && !adjuntos.length) || !motor.listo}
                onClick={() => lanzar("mejora")}>
                {ocupado ? <><span className="girando claro" /> Procesando…</> : <><Icono n="spark" size={18} /> Mejorar a v{detalle ? siguiente(detalle.version) : ""}</>}
              </button>
              {!ocupado && detalle && !respondidas && !adjuntos.length && <p className="falta">Responda al menos una pregunta o adjunte un documento del cliente.</p>}
              {detalle && proyecto && detalle.id !== proyecto.principal.id && (
                <p className="campo-ayuda">Está viendo {nombres.get(detalle.id)}; la versión actual del proyecto es v{proyecto.principal.version}. Mejorar desde aquí crea otra rama.</p>
              )}
            </>
          )}
          {error && <div className="banda-error"><Icono n="alert" size={16} /><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="Cerrar"><Icono n="x" size={14} /></button></div>}
        </div>
      </aside>
    </main>
  );
}
