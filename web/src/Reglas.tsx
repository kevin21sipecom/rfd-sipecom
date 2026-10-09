import { useEffect, useMemo, useState } from "react";
import { api, type Regla } from "./api";
import { Campo, Icono, Segmentado, Tarjeta } from "./components";

const VACIA: Regla = { id: null, texto: "", tipo: "evitar", seccion: "todo", patron: "", cliente: "", activa: true };

const SUGERENCIAS: Omit<Regla, "id" | "activa" | "cliente">[] = [
  { tipo: "evitar", seccion: "todo", texto: "No usar enumeraciones abiertas como «etc.», «entre otros» o «y otros»: enumerar los elementos concretos.", patron: "etc.|entre otros|y otros" },
  { tipo: "evitar", seccion: "esfuerzo", texto: "No estimar horas ni duración si no constan en las fuentes; dejarlas por estimar.", patron: "" },
  { tipo: "exigir", seccion: "criterios", texto: "Cada requerimiento debe incluir un criterio sobre el tiempo de espera agotado (timeout) de la integración.", patron: "timeout|tiempo de espera" },
  { tipo: "evitar", seccion: "todo", texto: "No usar anglicismos informales; usar el término en español.", patron: "setear|loguear|resetear|customizar" },
];

export function Reglas({ clienteActual }: { clienteActual: string }) {
  const [reglas, setReglas] = useState<Regla[]>([]);
  const [secciones, setSecciones] = useState<Record<string, string>>({});
  const [observaciones, setObservaciones] = useState<Record<string, string>>({});
  const [form, setForm] = useState<Regla>(VACIA);
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [filtro, setFiltro] = useState("");
  const [abiertos, setAbiertos] = useState<Record<string, boolean>>({ propias: true });

  const cargar = () => api.reglas().then((r) => {
    setReglas(r.reglas); setSecciones(r.secciones); setObservaciones(r.observaciones ?? {});
  }).catch((e: Error) => setError(e.message));
  useEffect(() => { cargar(); }, []);

  const accion = async (f: () => Promise<unknown>) => {
    setError("");
    setGuardando(true);
    try { await f(); await cargar(); } catch (e) { setError((e as Error).message); } finally { setGuardando(false); }
  };
  const guardar = (r: Regla) => accion(async () => { await api.guardarRegla(r); if (r === form) setForm(VACIA); });
  const eliminar = (r: Regla) => r.id != null && window.confirm(`¿Eliminar la regla ${etiqueta(r)}?`) && accion(() => api.eliminarRegla(r.id!));
  const restaurar = (r: Regla) => r.id != null && accion(() => api.restaurarRegla(r.id!));
  const grupoActivo = (lista: Regla[], activa: boolean) => accion(async () => {
    for (const r of lista.filter((x) => x.activa !== activa)) await api.guardarRegla({ ...r, activa });
  });

  const visibles = useMemo(() => {
    const f = filtro.trim().toLowerCase();
    return f ? reglas.filter((r) => `${r.codigo ?? ""} ${r.texto} ${r.cliente} ${secciones[r.seccion]}`.toLowerCase().includes(f)) : reglas;
  }, [reglas, filtro, secciones]);

  const grupos = useMemo(() => {
    const lista: { clave: string; titulo: string; reglas: Regla[] }[] = [];
    const propias = visibles.filter((r) => !r.predeterminada);
    lista.push({ clave: "propias", titulo: "Reglas propias del equipo", reglas: propias });
    for (const [obs, titulo] of Object.entries(observaciones)) {
      const rs = visibles.filter((r) => r.predeterminada && r.observacion === obs);
      if (rs.length) lista.push({ clave: obs, titulo: `Obs. ${obs} · ${titulo}`, reglas: rs });
    }
    return lista;
  }, [visibles, observaciones]);

  const activas = reglas.filter((r) => r.activa).length;
  const usadas = new Set(reglas.map((r) => r.texto.toLowerCase()));
  const buscando = filtro.trim().length > 0;

  return (
    <main className="contenido reglas">
      <div className="columna-form">
        <div className="intro">
          <h1>Reglas del equipo</h1>
          <p>Instrucciones que se agregan a cada llamada al modelo (generar, corregir, mejorar y preguntas). Incluye las 30 reglas predeterminadas del documento «Reglas y correcciones para el generador de RFD»: el RFD es para el cliente y no debe trasladar narrativas del agente, justificaciones de fuentes, datos del operador, coordinación interna ni anexos de trabajo. Si una regla tiene verificación, la rúbrica la comprueba y el mismo modelo corrige con el contexto completo.</p>
        </div>

        <Tarjeta numero={1} titulo={form.id == null ? "Nueva regla" : `Editar ${etiqueta(form)}`}
          ayuda={form.predeterminada ? "Regla predeterminada: puede ajustarla o desactivarla; «Restaurar» la devuelve al texto original."
            : "Escriba una instrucción concreta. Las reglas sin verificación sólo se inyectan al modelo."}>
          <div className="rejilla-campos">
            <Campo etiqueta="Tipo">
              <Segmentado valor={form.tipo} onCambio={(tipo) => setForm({ ...form, tipo })}
                opciones={[{ valor: "evitar", etiqueta: "Evitar", detalle: "lo que no debe hacer" }, { valor: "exigir", etiqueta: "Exigir", detalle: "lo que debe incluir" }]} />
            </Campo>
            <Campo etiqueta="Sección">
              <select value={form.seccion} onChange={(e) => setForm({ ...form, seccion: e.target.value })}>
                {Object.entries(secciones).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Campo>
            <Campo etiqueta="Regla *" ancho>
              <textarea rows={3} value={form.texto} onChange={(e) => setForm({ ...form, texto: e.target.value })}
                placeholder="p. ej. No mencionar países fuera del release en los criterios de aceptación." />
            </Campo>
            <Campo etiqueta="Verificación automática" ancho
              ayuda={form.tipo === "evitar"
                ? "Falla si alguno de estos términos aparece en la sección. Sepárelos con | o use re: para una expresión regular."
                : "Falla si no aparece ninguno de estos términos (en requerimientos, criterios y flujo se exige en cada RF)."}>
              <input value={form.patron} onChange={(e) => setForm({ ...form, patron: e.target.value })} spellCheck={false}
                placeholder="Opcional · etc.|entre otros   o   re:\b\d+ horas\b" />
            </Campo>
            <Campo etiqueta="Cliente" ayuda="Vacío: se aplica a todos los clientes.">
              <input value={form.cliente} onChange={(e) => setForm({ ...form, cliente: e.target.value })}
                placeholder={clienteActual || "Todos"} list="clientes-reglas" />
            </Campo>
            <datalist id="clientes-reglas">
              {[...new Set([clienteActual, ...reglas.map((r) => r.cliente)].filter(Boolean))].map((c) => <option key={c} value={c} />)}
            </datalist>
          </div>
          <div className="acciones-regla">
            <button type="button" className="boton primario" disabled={form.texto.trim().length < 5 || guardando} onClick={() => guardar(form)}>
              <Icono n="check" size={16} /> {form.id == null ? "Agregar regla" : "Guardar cambios"}
            </button>
            {form.id != null && <button type="button" className="boton" onClick={() => setForm(VACIA)}>Cancelar</button>}
          </div>
          {error && <p className="aviso-error">{error}</p>}
        </Tarjeta>

        <Tarjeta numero={2} titulo="Sugerencias" ayuda="Reglas propias frecuentes. Al elegir una se carga en el formulario para ajustarla.">
          <div className="sugerencias">
            {SUGERENCIAS.filter((s) => !usadas.has(s.texto.toLowerCase())).map((s) => (
              <button key={s.texto} type="button" className="sugerencia" onClick={() => setForm({ ...VACIA, ...s })}>
                <span className={`chip-tipo ${s.tipo}`}>{s.tipo === "evitar" ? "Evitar" : "Exigir"}</span>
                <span>{s.texto}</span>
              </button>
            ))}
          </div>
        </Tarjeta>
      </div>

      <aside className="columna-panel">
        <div className="panel">
          <div className="seccion-cab">
            <h2 className="panel-titulo">Reglas guardadas</h2>
            <span className="contador">{activas} activa(s) de {reglas.length}</span>
          </div>
          <div className="entrada-icono buscador"><Icono n="eye" size={15} />
            <input value={filtro} onChange={(e) => setFiltro(e.target.value)} placeholder="Buscar por código, texto o cliente" />
          </div>
          <div className="grupos-reglas">
            {grupos.map((g) => {
              const abierto = buscando || !!abiertos[g.clave];
              const activasGrupo = g.reglas.filter((r) => r.activa).length;
              return (
                <section key={g.clave} className="grupo-reglas">
                  <button type="button" className="grupo-reglas-cab" aria-expanded={abierto}
                    onClick={() => setAbiertos({ ...abiertos, [g.clave]: !abiertos[g.clave] })}>
                    <span className={`flecha ${abierto ? "abierta" : ""}`}>›</span>
                    <b>{g.titulo}</b>
                    <small>{activasGrupo}/{g.reglas.length}</small>
                  </button>
                  {abierto && g.clave !== "propias" && (
                    <div className="grupo-acciones">
                      <button type="button" className="enlace" disabled={guardando} onClick={() => grupoActivo(g.reglas, true)}>Activar todas</button>
                      <button type="button" className="enlace" disabled={guardando} onClick={() => grupoActivo(g.reglas, false)}>Desactivar todas</button>
                    </div>
                  )}
                  {abierto && !g.reglas.length && <p className="vacio">Aún no hay reglas propias. Agregue una o elija una sugerencia.</p>}
                  {abierto && (
                    <ul className="lista-reglas">
                      {g.reglas.map((r) => (
                        <li key={r.id} className={`regla ${r.activa ? "" : "inactiva"}`}>
                          <div className="regla-cab">
                            <b>{etiqueta(r)}</b>
                            <span className={`chip-tipo ${r.tipo}`}>{r.tipo === "evitar" ? "Evitar" : "Exigir"}</span>
                            <span className="regla-meta">{secciones[r.seccion] ?? r.seccion} · {r.cliente || "Todos los clientes"}</span>
                          </div>
                          <p>{r.texto}</p>
                          <div className="regla-pie">
                            <code title={r.patron || "Sin verificación automática"}>{r.patron ? "verifica: " + r.patron : "sólo instrucción"}</code>
                            <label className="interruptor mini">
                              <input type="checkbox" checked={r.activa} disabled={guardando} onChange={(e) => guardar({ ...r, activa: e.target.checked })} />
                              <span className="pista" />
                              <span>{r.activa ? "Activa" : "Inactiva"}</span>
                            </label>
                            <button type="button" className="enlace" onClick={() => setForm(r)}>Editar</button>
                            {r.predeterminada
                              ? <button type="button" className="enlace" onClick={() => restaurar(r)}>Restaurar</button>
                              : <button type="button" className="enlace peligro" onClick={() => eliminar(r)}>Eliminar</button>}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
        </div>
      </aside>
    </main>
  );
}

function etiqueta(r: Regla) {
  return r.codigo || (r.id != null ? `R${r.id}` : "regla");
}
