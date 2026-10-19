import { useCallback, useEffect, useState } from "react";
import { api, type ContextoCodigo, type Entorno, type Trabajo } from "./api";
import { Campo, Icono, Modal, Segmentado, Tarjeta, ZonaArchivos } from "./components";
import { Historial } from "./Historial";
import { useMotor } from "./Motor";
import { Progreso, ResultadoVista } from "./Panel";
import { Reglas } from "./Reglas";

const EXTENSIONES = [".txt", ".md", ".docx", ".pptx", ".pdf", ".xlsx"];

function Estado({ ok, texto, titulo }: { ok: boolean; texto: string; titulo?: string }) {
  return <span className={`pildora ${ok ? "ok" : "no"}`} title={titulo}><i />{texto}</span>;
}

export default function App() {
  const [entorno, setEntorno] = useState<Entorno | null>(null);
  const [transcripciones, setTranscripciones] = useState<File[]>([]);
  const [contextos, setContextos] = useState<File[]>([]);
  const [proyecto, setProyecto] = useState("");
  const [enfoque, setEnfoque] = useState("");
  const [cliente, setCliente] = useState("");
  const [codigo, setCodigo] = useState("");
  const [titulo, setTitulo] = useState("");
  const [fecha, setFecha] = useState("");
  const [tipo, setTipo] = useState<"existente" | "nuevo">("existente");
  const motor = useMotor(entorno?.clis ?? []);
  const [vista, setVista] = useState<"generar" | "historial" | "reglas">("generar");
  const [reglasAplicables, setReglasAplicables] = useState(0);
  const [rfdElegido, setRfdElegido] = useState<number | null>(null);
  const [publico, setPublico] = useState(false);
  const [estilos, setEstilos] = useState<File[]>([]);
  const [avances, setAvances] = useState<File[]>([]);
  const [revisarWord, setRevisarWord] = useState(true);
  const [trabajo, setTrabajo] = useState<Trabajo | null>(null);
  const [error, setError] = useState("");
  const [contexto, setContexto] = useState<ContextoCodigo | null>(null);
  const [cargandoContexto, setCargandoContexto] = useState(false);

  useEffect(() => {
    api.entorno().then((e) => { setEntorno(e); setFecha(e.fecha); }).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!trabajo || trabajo.estado !== "en_curso") return;
    const t = setInterval(() => {
      api.trabajo(trabajo.id).then(setTrabajo).catch((e: Error) => setError(e.message));
    }, 1500);
    return () => clearInterval(t);
  }, [trabajo]);

  useEffect(() => {
    if (vista !== "generar") return;
    const t = setTimeout(() => api.reglas(cliente).then((r) => setReglasAplicables(r.aplicables.length)).catch(() => undefined), 300);
    return () => clearTimeout(t);
  }, [cliente, vista]);

  const elegirCarpeta = async () => {
    try {
      const { ruta } = await api.elegirCarpeta();
      if (ruta) setProyecto(ruta);
    } catch (e) { setError((e as Error).message); }
  };

  const verContexto = useCallback(async () => {
    setCargandoContexto(true);
    setError("");
    try {
      setContexto(await api.contextoCodigo(proyecto, enfoque || titulo || proyecto.split(/[\\/]/).pop() || ""));
    } catch (e) { setError((e as Error).message); }
    finally { setCargandoContexto(false); }
  }, [proyecto, enfoque, titulo]);

  const faltantes = [
    !transcripciones.length && !contextos.length && !avances.length && "al menos un archivo",
    !cliente.trim() && "el cliente",
    !codigo.trim() && "el código",
    !motor.listo && "un motor disponible",
  ].filter(Boolean) as string[];
  const ocupado = trabajo?.estado === "en_curso";

  const generar = async () => {
    setError("");
    const f = new FormData();
    transcripciones.forEach((a) => f.append("transcripciones", a));
    contextos.forEach((a) => f.append("contextos", a));
    estilos.forEach((a) => f.append("estilos", a));
    avances.forEach((a) => f.append("avances", a));
    Object.entries({ cliente, codigo, titulo, fecha, proyecto, enfoque, tipo_proyecto: tipo })
      .forEach(([k, v]) => f.append(k, v));
    motor.agregar(f);
    f.append("publico", String(publico));
    f.append("revisar_word", String(revisarWord && !!entorno?.word));
    try {
      const { id } = await api.generar(f);
      setTrabajo(await api.trabajo(id));
    } catch (e) { setError((e as Error).message); }
  };

  const demostracion = async () => {
    setError("");
    try {
      const { id } = await api.demo();
      setTrabajo(await api.trabajo(id));
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <div className="app">
      <header className="barra">
        <div className="marca">
          <span className="logo"><Icono n="doc" size={18} /></span>
          <div>
            <strong>Generador de RFD</strong>
            <span>SIPECOM · Requerimiento Funcional Detallado</span>
          </div>
        </div>
        <nav className="pestanas-app" role="tablist">
          {(["generar", "historial", "reglas"] as const).map((v) => (
            <button key={v} type="button" role="tab" aria-selected={vista === v} className={vista === v ? "activa" : ""} onClick={() => setVista(v)}>
              {{ generar: "Generar", historial: "Historial y mejoras", reglas: "Reglas" }[v]}
            </button>
          ))}
        </nav>
        {entorno && (
          <div className="estados">
            {entorno.clis.map((c) => (
              <Estado key={c.id} ok={!!c.ruta} texto={c.nombre} titulo={c.ruta ?? `${c.nombre}: no encontrado en PATH`} />
            ))}
            <Estado ok={!!(entorno.codegraph || entorno.repomix)} texto={entorno.codegraph ? "CodeGraph" : entorno.repomix ? "Repomix" : "CodeGraph"}
              titulo={entorno.codegraph ?? entorno.repomix ?? "Opcional: npm i -g @colbymchenry/codegraph"} />
            <Estado ok={entorno.plantilla} texto="Plantilla" />
          </div>
        )}
      </header>

      {vista === "reglas" && <Reglas clienteActual={cliente} />}
      {vista === "historial" && <Historial motor={motor} wordDisponible={!!entorno?.word} seleccionInicial={rfdElegido} />}
      <main className="contenido" hidden={vista !== "generar"}>
        <div className="columna-form">
          <div className="intro">
            <h1>Del acta de reunión al RFD en Word</h1>
            <p>Cargue especificaciones, actas o presentaciones, apunte a los repositorios si el sistema ya existe y obtenga un RFD trazable con la plantilla SIPECOM: cada documento se analiza por separado, se cruzan las fuentes para detectar contradicciones y Word revisa el resultado.</p>
          </div>

          <Tarjeta numero={1} titulo="Fuentes" ayuda="Cargue al menos un archivo. La transcripción es opcional; el contexto puede ser actas, especificaciones o presentaciones.">
            <div className="rejilla-2">
              <ZonaArchivos titulo="Transcripciones" descripcion="Opcional · reunión con el cliente" archivos={transcripciones}
                aceptar={EXTENSIONES} onCambio={setTranscripciones} />
              <ZonaArchivos titulo="Contexto del proyecto" descripcion="Documentos y presentaciones" archivos={contextos}
                aceptar={EXTENSIONES} onCambio={setContextos} />
            </div>
            <div className="bloque-estilo">
              <ZonaArchivos titulo="RFD en avance" descripcion="Opcional · trabajo previo que la IA debe continuar" archivos={avances}
                aceptar={EXTENSIONES} onCambio={setAvances} />
              <p className="campo-ayuda">Se conserva lo ya redactado, se completa lo que falta y se imita la forma de trabajar del autor. Si contradice otras fuentes, queda registrado en «definiciones».</p>
            </div>
            <div className="bloque-estilo">
              <ZonaArchivos titulo="Referencias de estilo" descripcion="Opcional · RFD aprobados de otros proyectos" archivos={estilos}
                aceptar={EXTENSIONES} onCambio={setEstilos} />
              <p className="campo-ayuda">Sólo se imita su estructura, profundidad y forma de redactar. Su contenido no se incorpora: la revisión avisa si se filtran nombres o datos de la referencia.</p>
            </div>
          </Tarjeta>

          <Tarjeta numero={2} titulo="Código del proyecto" ayuda="Opcional. Puede ser una carpeta con varios repositorios: se inventaría cada uno (stack, servicios, procedimientos) y CodeGraph aporta el código relacionado con cada interfaz."
            extra={<span className="etiqueta-opcional">Opcional</span>}>
            <div className="fila-carpeta">
              <div className="entrada-icono">
                <Icono n="folder" size={16} />
                <input value={proyecto} onChange={(e) => setProyecto(e.target.value)} placeholder="C:\ruta\al\proyecto" spellCheck={false} />
              </div>
              <button type="button" className="boton" onClick={elegirCarpeta}>Examinar</button>
              <button type="button" className="boton" disabled={!proyecto.trim() || cargandoContexto} onClick={verContexto}>
                {cargandoContexto ? <span className="girando" /> : <Icono n="eye" size={16} />} Ver contexto
              </button>
            </div>
            <Campo etiqueta="Enfoque de búsqueda en el código" ayuda="Por defecto se usan los temas detectados en cada documento." ancho>
              <input value={enfoque} onChange={(e) => setEnfoque(e.target.value)} placeholder="p. ej. registro y asignación de solicitudes" />
            </Campo>
          </Tarjeta>

          <Tarjeta numero={3} titulo="Datos del RFD">
            <div className="rejilla-campos">
              <Campo etiqueta="Cliente *"><input value={cliente} onChange={(e) => setCliente(e.target.value)} placeholder="Nombre del cliente" /></Campo>
              <Campo etiqueta="Código RFD *"><input value={codigo} onChange={(e) => setCodigo(e.target.value)} placeholder="RFD-001" /></Campo>
              <Campo etiqueta="Título" ayuda="Si se deja vacío, se deduce de las fuentes." ancho>
                <input value={titulo} onChange={(e) => setTitulo(e.target.value)} placeholder="Opcional" />
              </Campo>
              <Campo etiqueta="Fecha"><input value={fecha} onChange={(e) => setFecha(e.target.value)} /></Campo>
              <Campo etiqueta="Tipo de proyecto">
                <Segmentado valor={tipo} onCambio={setTipo}
                  opciones={[{ valor: "existente", etiqueta: "Existente" }, { valor: "nuevo", etiqueta: "Nuevo" }]} />
              </Campo>
            </div>
          </Tarjeta>
        </div>

        <aside className="columna-panel">
          <div className="panel">
            {trabajo?.estado === "listo" ? (
              <ResultadoVista trabajo={trabajo} onNuevo={() => setTrabajo(null)}
                onPreguntas={(id) => { setRfdElegido(id); setVista("historial"); }} />
            ) : (
              <>
                <h2 className="panel-titulo"><span className="numero">4</span> Motor y generación</h2>
                {motor.vista}
                <label className="interruptor">
                  <input type="checkbox" checked={publico} onChange={(e) => setPublico(e.target.checked)} />
                  <span className="pista" />
                  <span>
                    Modo público
                    <small>Bloquea el Word si quedan pendientes o datos sin confirmar.</small>
                  </span>
                </label>

                {entorno?.word && (
                  <label className="interruptor">
                    <input type="checkbox" checked={revisarWord} onChange={(e) => setRevisarWord(e.target.checked)} />
                    <span className="pista" />
                    <span>
                      Revisar con Microsoft Word
                      <small>Actualiza el índice con páginas, exporta PDF y detecta páginas vacías.</small>
                    </span>
                  </label>
                )}

                <ul className="lista-control">
                  <li className={transcripciones.length ? "ok" : ""}><Icono n="check" size={14} />{transcripciones.length ? `${transcripciones.length} transcripción(es)` : "Sin transcripción (opcional)"}</li>
                  <li className={contextos.length ? "ok" : ""}><Icono n="check" size={14} />{contextos.length} documento(s) de contexto</li>
                  <li className={avances.length ? "ok" : ""}><Icono n="check" size={14} />{avances.length ? `${avances.length} RFD en avance a continuar` : "Sin RFD en avance (opcional)"}</li>
                  <li className={estilos.length ? "ok" : ""}><Icono n="check" size={14} />{estilos.length ? `${estilos.length} referencia(s) de estilo` : "Sin referencia de estilo (opcional)"}</li>
                  <li className={proyecto.trim() ? "ok" : ""}><Icono n="check" size={14} />{proyecto.trim() ? "Código del proyecto incluido" : "Sin código del proyecto"}</li>
                  <li className={cliente && codigo ? "ok" : ""}><Icono n="check" size={14} />Cliente y código</li>
                  <li className={reglasAplicables ? "ok" : ""}><Icono n="check" size={14} />
                    <button type="button" className="enlace" onClick={() => setVista("reglas")}>
                      {reglasAplicables ? `${reglasAplicables} regla(s) del equipo` : "Sin reglas del equipo"}
                    </button>
                  </li>
                </ul>

                {trabajo && <Progreso trabajo={trabajo} conCodigo={!!proyecto.trim()} conWord={revisarWord && !!entorno?.word} />}

                <button type="button" className="boton primario grande" disabled={faltantes.length > 0 || ocupado} onClick={generar}>
                  {ocupado ? <><span className="girando claro" /> Generando…</> : <><Icono n="spark" size={18} /> Generar RFD</>}
                </button>
                {faltantes.length > 0 && !ocupado && <p className="falta">Falta {faltantes.join(", ")}.</p>}
                <button type="button" className="boton fantasma ancho" disabled={ocupado} onClick={demostracion}>
                  <Icono n="play" size={14} /> Ver demostración sin modelo
                </button>
              </>
            )}
            {error && <div className="banda-error"><Icono n="alert" size={16} /><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="Cerrar"><Icono n="x" size={14} /></button></div>}
          </div>
          {entorno && <p className="pie">Los archivos se guardan en <code>{entorno.salidas}</code></p>}
        </aside>
      </main>

      {contexto && (
        <Modal titulo="Contexto del código" subtitulo={`${contexto.nombre} · ${contexto.caracteres.toLocaleString("es")} caracteres`} onCerrar={() => setContexto(null)}>
          <pre className="codigo">{contexto.contenido}</pre>
        </Modal>
      )}
    </div>
  );
}
