import { useEffect, useState } from "react";
import { api, type Paso, type Trabajo } from "./api";
import { Icono } from "./components";
import { EnviarEstimador } from "./Estimador";

const PASOS: { id: Paso; texto: string }[] = [
  { id: "fuentes", texto: "Leyendo documentos y referencias" },
  { id: "analisis", texto: "Analizando cada documento" },
  { id: "codigo", texto: "Revisando repositorios y código" },
  { id: "modelo", texto: "Redactando el RFD" },
  { id: "calidad", texto: "Revisión editorial con la rúbrica de referencia" },
  { id: "word", texto: "Armando el Word con la plantilla SIPECOM" },
  { id: "revision", texto: "Revisión con Microsoft Word (índice y PDF)" },
];

export const PASOS_MEJORA: { id: Paso; texto: string }[] = [
  { id: "base", texto: "Cargando el RFD base del historial" },
  { id: "respuestas", texto: "Reuniendo las respuestas del cliente" },
  { id: "modelo", texto: "Adaptando el RFD a las respuestas" },
  { id: "calidad", texto: "Revisión editorial con la rúbrica de referencia" },
  { id: "word", texto: "Armando la nueva versión del Word" },
  { id: "revision", texto: "Revisión con Microsoft Word (índice y PDF)" },
];

export const PASOS_CONTINUAR: { id: Paso; texto: string }[] = [
  { id: "base", texto: "Cargando el RFD en avance del historial" },
  { id: "fuentes", texto: "Leyendo el contexto adicional" },
  { id: "modelo", texto: "Completando lo que falta sin tocar lo escrito" },
  { id: "calidad", texto: "Revisión editorial sólo de lo agregado" },
  { id: "word", texto: "Armando la nueva versión del Word" },
  { id: "revision", texto: "Revisión con Microsoft Word (índice y PDF)" },
];

export const PASOS_IMPORTAR: { id: Paso; texto: string }[] = [
  { id: "base", texto: "Leyendo el Word en avance" },
  { id: "modelo", texto: "Reconstruyendo la estructura del RFD" },
  { id: "calidad", texto: "Midiendo qué le falta al RFD" },
];

const ORDEN: Paso[] = ["cola", "base", "respuestas", "fuentes", "analisis", "codigo", "modelo", "calidad", "word", "revision", "listo"];

function useSegundos(inicio: number, fin?: number) {
  const [ahora, setAhora] = useState(Date.now() / 1000);
  useEffect(() => {
    if (fin) return;
    const t = setInterval(() => setAhora(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [fin]);
  const s = Math.max(0, Math.round((fin ?? ahora) - inicio));
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
}

export function Progreso({ trabajo, conCodigo, conWord, pasos: lista = PASOS }: {
  trabajo: Trabajo; conCodigo: boolean; conWord: boolean; pasos?: { id: Paso; texto: string }[];
}) {
  const transcurrido = useSegundos(trabajo.inicio, trabajo.fin);
  const actual = ORDEN.indexOf(trabajo.paso);
  const pasos = lista.filter((p) => (p.id !== "codigo" || conCodigo) && (p.id !== "revision" || conWord));
  return (
    <div className="progreso">
      <div className="progreso-cab">
        <strong>{trabajo.estado === "error" ? "No se generó el RFD" : "Generando…"}</strong>
        <span>{transcurrido}</span>
      </div>
      <ol>
        {pasos.map((p) => {
          const i = ORDEN.indexOf(p.id);
          const estado = trabajo.estado === "error" && i === actual ? "fallo" : i < actual ? "hecho" : i === actual ? "activo" : "";
          return (
            <li key={p.id} className={estado}>
              <span className="punto">{estado === "hecho" ? <Icono n="check" size={12} /> : estado === "fallo" ? <Icono n="x" size={12} /> : null}</span>
              <span className="paso-texto">
                {p.texto}
                {(p.id === "modelo" || p.id === "analisis") && estado === "activo" && <small> · {trabajo.modelo}</small>}
                {estado === "activo" && trabajo.detalle && trabajo.detalle !== p.texto && <em>{trabajo.detalle}</em>}
              </span>
            </li>
          );
        })}
      </ol>
      {trabajo.fuentes && (
        <ul className="fuentes-usadas">
          {trabajo.fuentes.map((f) => (
            <li key={f.id}><b>{f.id}</b> {f.nombre} <span>{f.categoria} · {f.caracteres.toLocaleString("es")} car.</span></li>
          ))}
        </ul>
      )}
      {trabajo.error && <pre className="error-detalle">{trabajo.error}</pre>}
    </div>
  );
}

type Pestana = "requerimientos" | "cambios" | "preguntas" | "calidad" | "definiciones" | "pendientes" | "informe";

export function ResultadoVista({ trabajo, onNuevo, textoNuevo = "Generar otro RFD", onPreguntas }: {
  trabajo: Trabajo; onNuevo: () => void; textoNuevo?: string; onPreguntas?: (rfdId: number) => void;
}) {
  const r = trabajo.resultado!;
  const preguntas = r.preguntas_cliente ?? [];
  const cambios = r.cambios ?? [];
  const [pestana, setPestana] = useState<Pestana>(cambios.length ? "cambios" : "requerimientos");
  const transcurrido = useSegundos(trabajo.inicio, trabajo.fin);
  const limpio = r.hallazgos.length === 0;

  return (
    <div className="resultado">
      <div className="resultado-cab">
        <span className="sello"><Icono n="check" size={16} /></span>
        <div>
          <small>{r.codigo} · {r.cliente}{r.version ? ` · versión ${r.version}` : ""}</small>
          <h3>{r.titulo || "RFD generado"}</h3>
          <p>{r.archivo}{r.paginas ? ` · ${r.paginas} páginas` : ""} · {transcurrido}</p>
        </div>
      </div>

      {trabajo.proveedor !== "demo" && (
        <div className="uso-modelo">
          <span>Modelo <code>{trabajo.uso?.modelos?.join(", ") || trabajo.modelo}</code></span>
          {trabajo.uso?.llamadas ? <span>{trabajo.uso.llamadas} llamadas</span> : null}
          {trabajo.uso?.costo_usd == null && trabajo.uso?.tokens_entrada ? (
            <span>{(trabajo.uso.tokens_entrada / 1000).toFixed(0)}k tokens entrada · {((trabajo.uso.tokens_salida ?? 0) / 1000).toFixed(0)}k salida</span>
          ) : null}
          {trabajo.uso?.costo_usd != null && <span>Costo {trabajo.uso.costo_usd.toLocaleString("es", { style: "currency", currency: "USD", maximumFractionDigits: 3 })}</span>}
        </div>
      )}

      <div className="metricas">
        <div><b>{r.requerimientos.length}</b><span>requerimientos</span></div>
        {r.calidad && (
          <div className={r.calidad.puntaje >= r.calidad.umbral ? "ok" : "atencion"}>
            <b>{Math.round(r.calidad.puntaje * 100)}%</b><span>nivel narrativo</span>
          </div>
        )}
        <div className={r.definiciones.length ? "atencion" : ""}><b>{r.definiciones.length}</b><span>definiciones</span></div>
        <div className={limpio ? "ok" : "atencion"}><b>{r.hallazgos.length}</b><span>hallazgos</span></div>
      </div>

      <div className="acciones-resultado">
        <a className="boton primario" href={api.archivo(trabajo.id, "docx")}><Icono n="download" size={16} /> Descargar Word</a>
        <button type="button" className="boton" onClick={() => api.abrir(trabajo.id, "docx")}><Icono n="doc" size={16} /> Abrir</button>
        <button type="button" className="boton" onClick={() => api.abrir(trabajo.id, "carpeta")}><Icono n="folder" size={16} /> Carpeta</button>
      </div>
      <div className="enlaces-secundarios">
        {r.pdf && <a href={api.archivo(trabajo.id, "pdf")}>PDF</a>}
        {r.pdf && <button type="button" className="enlace" onClick={() => api.abrir(trabajo.id, "pdf")}>Abrir PDF</button>}
        <a href={api.archivo(trabajo.id, "json")}>JSON</a>
        {r.cuestionario && <a href={api.archivo(trabajo.id, "cuestionario")}>Cuestionario para el cliente</a>}
        {trabajo.proveedor !== "demo" && !trabajo.tipo && <a href={api.archivo(trabajo.id, "analisis")}>Análisis por documento</a>}
        <a href={api.archivo(trabajo.id, "revision")}>Informe de revisión (.md)</a>
      </div>

      {r.rfd_id != null && (
        <EnviarEstimador rfdId={r.rfd_id} codigo={r.codigo} version={r.version ?? "0.1"} proyecto={r.proyecto} />
      )}

      {r.word && (
        <div className="nota-revision"><Icono n="alert" size={16} /><span>No se revisó con Word: {r.word}</span></div>
      )}

      {!limpio && (
        <div className="nota-revision">
          <Icono n="alert" size={16} />
          <span>Borrador interno: resuelva los hallazgos y las preguntas antes de compartirlo con el cliente.</span>
        </div>
      )}

      <div className="pestanas" role="tablist">
        {([...(cambios.length ? ["cambios"] : []), "requerimientos", ...(preguntas.length ? ["preguntas"] : []), ...(r.calidad ? ["calidad"] : []),
           "definiciones", "pendientes", "informe"] as Pestana[]).map((p) => (
          <button key={p} type="button" role="tab" aria-selected={pestana === p}
            className={pestana === p ? "activa" : ""} onClick={() => setPestana(p)}>
            {{ cambios: `Cambios (${cambios.length})`, preguntas: `Preguntas (${preguntas.length})`, requerimientos: "Requerimientos", calidad: "Calidad", definiciones: `Definiciones (${r.definiciones.length})`, pendientes: "Pendientes", informe: "Informe" }[p]}
          </button>
        ))}
      </div>

      <div className="pestana-cuerpo">
        {pestana === "requerimientos" && (
          <ul className="lista-rf">
            {r.requerimientos.map((q) => (
              <li key={q.id}>
                <span className="rf-id">{q.id}</span>
                <div>
                  <p>{q.nombre}</p>
                  <div className="evidencias">
                    {q.evidencias.length ? q.evidencias.map((e) => <code key={e}>{e}</code>) : <em>Sin evidencia</em>}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {pestana === "cambios" && (
          <div className="lista-pendientes">
            {cambios.map((c, i) => (
              <div key={i} className="pendiente"><p><b>{c.pregunta}</b> · {c.seccion}</p><small>{c.cambio}</small></div>
            ))}
          </div>
        )}
        {pestana === "preguntas" && (
          <div className="lista-pendientes">
            {onPreguntas && r.rfd_id != null && (
              <button type="button" className="boton ancho" onClick={() => onPreguntas(r.rfd_id!)}>
                <Icono n="refresh" size={15} /> Responder y mejorar el RFD
              </button>
            )}
            {preguntas.map((x) => (
              <div key={x.id} className="pendiente"><p><b>{x.id} · {x.tema}</b></p><small>{x.contexto}</small><p>{x.pregunta}</p></div>
            ))}
          </div>
        )}
        {pestana === "calidad" && r.calidad && (
          <div className="lista-pendientes">
            <p className="nota-calidad">
              Rúbrica calibrada con el RFD de referencia aprobado · umbral {Math.round(r.calidad.umbral * 100)}% ·
              {" "}{r.calidad.rondas} ronda(s) de revisión editorial
            </p>
            {[...r.calidad.criterios].sort((a, b) => Number(a.ok) - Number(b.ok)).map((c) => (
              <div key={c.id} className={c.ok ? "supuesto" : "hallazgo"}>
                <b>{c.ok ? "✔" : "✘"} {c.id}</b> {c.descripcion}
                {c.detalle && <small className="detalle-calidad">{c.detalle}</small>}
              </div>
            ))}
          </div>
        )}
        {pestana === "definiciones" && (
          <div className="lista-pendientes">
            {r.definiciones.map((x) => (
              <div key={x.id} className="pendiente">
                <p><b>{x.id}</b> — {x.titulo}</p>
                <small>{x.descripcion}</small>
                {x.evidencias.length > 0 && <div className="evidencias">{x.evidencias.map((e) => <code key={e}>{e}</code>)}</div>}
              </div>
            ))}
            {!r.definiciones.length && <p className="vacio">No se detectaron contradicciones entre las fuentes.</p>}
          </div>
        )}
        {pestana === "pendientes" && (
          <div className="lista-pendientes">
            {r.hallazgos.map((h) => (
              <div key={h.codigo} className="hallazgo"><b>{h.codigo}</b> {h.mensaje}</div>
            ))}
            {r.pendientes.map((p, i) => (
              <div key={i} className="pendiente"><p>{p.pregunta}</p><small>{p.motivo}</small></div>
            ))}
            {r.supuestos.length > 0 && <h4>Supuestos</h4>}
            {r.supuestos.map((s, i) => <div key={`s${i}`} className="supuesto">{s}</div>)}
            {!r.pendientes.length && !r.hallazgos.length && !r.supuestos.length && <p className="vacio">Sin pendientes.</p>}
          </div>
        )}
        {pestana === "informe" && <pre className="informe">{r.revision_md}</pre>}
      </div>

      <button type="button" className="boton fantasma ancho" onClick={onNuevo}><Icono n="refresh" size={16} /> {textoNuevo}</button>
    </div>
  );
}
