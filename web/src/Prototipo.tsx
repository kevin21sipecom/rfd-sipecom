import { useCallback, useEffect, useState } from "react";
import { api, type ComandoDetectado, type ModoPrototipo, type PrototipoDetalle, type RfdDetalle, type Trabajo } from "./api";
import { Campo, Icono, Segmentado, ZonaArchivos } from "./components";
import type { Motor } from "./Motor";

const ESTADO_PROCESO: Record<string, string> = { detenido: "Detenido", iniciando: "Iniciando…", activo: "En ejecución", error: "Terminó con error" };

/** Los dos últimos niveles del título («Portal Público: Consulta de Facturas › Ventana principal»). */
const corto = (titulo: string) => titulo.split(" › ").slice(-2).join(" › ") || "Sin título";

/** Prototipo de UI del RFD: con las maquetas del Word («documento») o sobre el sistema en ejecución («proyecto»). */
export function PanelPrototipo({ rfd, motor }: { rfd: RfdDetalle; motor: Motor }) {
  const [modo, setModo] = useState<ModoPrototipo>("documento");
  const [proto, setProto] = useState<PrototipoDetalle | null>(null);
  const [cargando, setCargando] = useState(true);
  const [elegidas, setElegidas] = useState<string[]>([]);
  const [texto, setTexto] = useState("");
  const [trabajo, setTrabajo] = useState<Trabajo | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [ruta, setRuta] = useState("");
  const [comandos, setComandos] = useState<ComandoDetectado[]>([]);
  const [comando, setComando] = useState(0);
  const [urlExterna, setUrlExterna] = useState("");
  const [rutasCaptura, setRutasCaptura] = useState("/");
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");

  const abrir = useCallback(async (id: string) => {
    const d = await api.prototipo(id);
    setProto(d);
    setVersion((v) => (v && d.versiones.includes(v) ? v : d.versiones[d.versiones.length - 1] ?? null));
    return d;
  }, []);

  // El prototipo más reciente de este RFD en el modo elegido (la lista viene ordenada del más nuevo al más viejo).
  useEffect(() => {
    setProto(null); setCargando(true); setTrabajo(null); setAviso(""); setError(""); setComandos([]);
    api.prototipos()
      .then((lista) => lista.find((p) => p.rfd?.id === rfd.id && p.modo === modo))
      .then((p) => (p ? abrir(p.id).then((d) => setElegidas(d.imagenes.map((m) => m.archivo))) : undefined))
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false));
  }, [rfd.id, modo, abrir]);

  useEffect(() => {
    if (proto?.modo !== "proyecto" || !proto.ruta) return;
    api.detectarComandos(proto.ruta).then((r) => setComandos(r.comandos)).catch(() => setComandos([]));
  }, [proto?.id, proto?.modo, proto?.ruta]);

  // Sigue el trabajo en curso (versión o captura) y el arranque del proyecto hasta que tenga URL.
  useEffect(() => {
    if (!proto) return;
    const enCurso = trabajo?.estado === "en_curso";
    if (!enCurso && proto.proceso.estado !== "iniciando") return;
    const t = setInterval(async () => {
      try {
        if (trabajo && enCurso) {
          const x = await api.trabajo(trabajo.id);
          setTrabajo(x);
          if (x.estado === "listo") {
            const d = await abrir(proto.id);
            const nueva = (x.resultado as unknown as { version?: number } | undefined)?.version;
            if (nueva) setVersion(nueva);
            else if (x.tipo === "captura") setAviso(`Se capturaron ${d.captura.pantallas.length} pantalla(s).`);
          }
        } else {
          await abrir(proto.id);
        }
      } catch (e) { setError((e as Error).message); }
    }, 1500);
    return () => clearInterval(t);
  }, [proto, trabajo, abrir]);

  const ejecutar = async (accion: () => Promise<unknown>) => {
    setError(""); setAviso("");
    try { await accion(); } catch (e) { setError((e as Error).message); }
  };

  const crear = () => ejecutar(async () => {
    const { id } = await api.crearPrototipo(modo, rfd.id, modo === "proyecto" ? ruta.trim() : "");
    const d = await abrir(id);
    setElegidas(d.imagenes.map((m) => m.archivo));
  });

  const subir = (archivos: File[]) => ejecutar(async () => {
    if (!proto || !archivos.length) return;
    const { imagenes } = await api.subirMaquetas(proto.id, archivos);
    const nuevas = imagenes.map((m) => m.archivo).filter((a) => !proto.imagenes.some((m) => m.archivo === a));
    setProto({ ...proto, imagenes });
    setElegidas((e) => [...e, ...nuevas]);
    setAviso(nuevas.length ? `${nuevas.length} maqueta(s) nueva(s).` : "El documento no agregó maquetas nuevas.");
  });

  const enviar = () => ejecutar(async () => {
    if (!proto) return;
    const f = new FormData();
    motor.agregar(f);
    f.append("texto", texto.trim());
    if (proto.modo === "documento") f.append("imagenes", elegidas.join(","));
    const { id } = await api.mensajePrototipo(proto.id, f);
    setTrabajo(await api.trabajo(id));
    setTexto("");
  });

  const levantar = () => ejecutar(async () => {
    if (!proto) return;
    const c = comandos[comando];
    const estado = urlExterna.trim() ? await api.levantar(proto.id, { url: urlExterna.trim() })
      : await api.levantar(proto.id, { comando: c.comando, url_esperada: c.url_esperada });
    setProto({ ...proto, proceso: estado });
  });

  const detener = () => ejecutar(async () => {
    if (proto) setProto({ ...proto, proceso: await api.detener(proto.id) });
  });

  const capturar = () => ejecutar(async () => {
    if (!proto) return;
    const rutas = rutasCaptura.split(",").map((r) => r.trim()).filter(Boolean);
    const { id } = await api.capturar(proto.id, rutas.length ? rutas : ["/"]);
    setTrabajo(await api.trabajo(id));
  });

  const adjuntar = () => ejecutar(async () => {
    if (!proto || version == null) return;
    const r = await api.adjuntarPrototipo(proto.id, version);
    setAviso(`La versión ${r.version} quedó junto al Word del RFD (${r.archivo}).`
      + (r.pantallas ? ` ${r.pantallas} pantalla(s) capturada(s): la próxima versión del Word las inserta en sus ventanas.` : ""));
    if (r.aviso) setError(r.aviso);
  });

  const alternar = (archivo: string) =>
    setElegidas((e) => (e.includes(archivo) ? e.filter((x) => x !== archivo) : [...e, archivo]));

  const ocupado = trabajo?.estado === "en_curso";
  const proceso = proto?.proceso;
  const sinMaquetas = proto?.modo === "documento" && proto.imagenes.length === 0;
  const puedeEnviar = !!proto && !ocupado && !!texto.trim() && motor.listo && (proto.modo !== "documento" || elegidas.length > 0 || sinMaquetas);

  return (
    <>
      <h2 className="panel-titulo"><Icono n="eye" size={16} /> Prototipo de UI</h2>
      <Segmentado valor={modo} onCambio={setModo} opciones={[
        { valor: "documento", etiqueta: "Solo documento", detalle: "maquetas del Word" },
        { valor: "proyecto", etiqueta: "Proyecto", detalle: "levantar y capturar" },
      ]} />
      <p className="campo-ayuda">
        {modo === "documento"
          ? "Se toman las maquetas del Word del RFD (y de otros Word que agregue). Elija cuáles usar: la IA las reproduce en un HTML navegable y diseña con el mismo estilo las pantallas que no tienen maqueta."
          : "Se levanta el sistema existente (o se indica la URL donde ya corre) y Playwright captura sus pantallas reales con Chrome o Edge. La IA construye el cambio sobre ese diseño."}
      </p>

      {cargando && <p className="vacio">Cargando…</p>}

      {!cargando && !proto && (
        <>
          {modo === "proyecto" && (
            <Campo etiqueta="Carpeta del sistema existente *" ancho>
              <div className="fila-entrada">
                <input value={ruta} onChange={(e) => setRuta(e.target.value)} placeholder="C:\proyectos\portal-proveedores" />
                <button type="button" className="boton" onClick={() => ejecutar(async () => {
                  const r = await api.elegirCarpeta();
                  if (r.ruta) setRuta(r.ruta);
                })}><Icono n="folder" size={15} /></button>
              </div>
            </Campo>
          )}
          <button type="button" className="boton primario grande" disabled={modo === "proyecto" && !ruta.trim()} onClick={crear}>
            <Icono n="spark" size={18} /> {modo === "documento" ? "Leer las maquetas del RFD" : "Vincular el proyecto"}
          </button>
        </>
      )}

      {proto?.modo === "documento" && (
        <>
          <div className="seccion-cab">
            <h3>Maquetas del documento</h3>
            <small>{elegidas.length} de {proto.imagenes.length} elegida(s)</small>
          </div>
          {sinMaquetas ? (
            <p className="campo-ayuda">El Word de este RFD no trae maquetas. Agregue un Word con imágenes o describa la pantalla: se diseñará a partir de las ventanas y campos del RFD.</p>
          ) : (
            <>
              <div className="acciones-maquetas">
                <button type="button" className="boton fantasma" onClick={() => setElegidas(proto.imagenes.map((m) => m.archivo))}>Todas</button>
                <button type="button" className="boton fantasma" onClick={() => setElegidas([])}>Ninguna</button>
              </div>
              <div className="maquetas">
                {proto.imagenes.map((m) => (
                  <label key={m.archivo} className={`maqueta ${elegidas.includes(m.archivo) ? "activa" : ""}`} title={`${m.titulo}\n${m.contexto}`}>
                    <input type="checkbox" checked={elegidas.includes(m.archivo)} onChange={() => alternar(m.archivo)} />
                    <img src={api.imagenPrototipo(proto.id, m.archivo)} alt={corto(m.titulo)} loading="lazy" />
                    <span>{corto(m.titulo)}</span>
                  </label>
                ))}
              </div>
            </>
          )}
          <ZonaArchivos titulo="Otros Word con maquetas" descripcion="Opcional · especificaciones o actas con imágenes de pantallas" archivos={[]}
            aceptar={[".docx"]} onCambio={subir} />
        </>
      )}

      {proto?.modo === "proyecto" && proceso && (
        <>
          <div className="seccion-cab">
            <h3>Sistema existente</h3>
            <span className={`chip-estado ${proceso.estado}`}>{ESTADO_PROCESO[proceso.estado]}</span>
          </div>
          <p className="ruta-proyecto"><code>{proto.ruta}</code></p>
          {proceso.estado === "activo" || proceso.estado === "iniciando" ? (
            <>
              {proceso.url && <p className="campo-ayuda">Disponible en <a href={proceso.url} target="_blank" rel="noreferrer">{proceso.url}</a></p>}
              <button type="button" className="boton ancho" onClick={detener}><Icono n="x" size={15} /> Detener</button>
            </>
          ) : (
            <>
              {comandos.length > 0 && (
                <Campo etiqueta="Comando para levantarlo" ayuda="Levantar ejecuta el código del proyecto en este equipo: revise el comando antes de iniciarlo." ancho>
                  <select value={comando} onChange={(e) => setComando(Number(e.target.value))}>
                    {comandos.map((c, i) => <option key={i} value={i}>{c.etiqueta}{c.url_esperada ? ` · ${c.url_esperada}` : ""}</option>)}
                  </select>
                </Campo>
              )}
              <Campo etiqueta="¿Ya está corriendo?" ayuda="Indique su URL y no se iniciará ningún proceso." ancho>
                <input value={urlExterna} onChange={(e) => setUrlExterna(e.target.value)} placeholder="http://localhost:5173" />
              </Campo>
              <button type="button" className="boton ancho" disabled={!urlExterna.trim() && !comandos.length} onClick={levantar}>
                <Icono n="play" size={15} /> {urlExterna.trim() ? "Usar esta URL" : "Levantar el proyecto"}
              </button>
              {!comandos.length && !urlExterna.trim() && <p className="falta">No se detectó cómo levantarlo: indique la URL donde ya corre.</p>}
            </>
          )}
          {proceso.log.length > 0 && <pre className="log-proceso">{proceso.log.slice(-8).join("\n")}</pre>}
          <Campo etiqueta="Pantallas a capturar" ayuda="Rutas separadas por coma, p. ej. «/, /tesoreria/facturas»." ancho>
            <input value={rutasCaptura} onChange={(e) => setRutasCaptura(e.target.value)} />
          </Campo>
          <button type="button" className="boton ancho" disabled={proceso.estado !== "activo" || ocupado} onClick={capturar}>
            <Icono n="eye" size={15} /> Capturar con Playwright
          </button>
          {proto.captura.pantallas.length > 0 && (
            <div className="maquetas">
              {proto.captura.pantallas.map((p) => (
                <a key={p.imagen} className="maqueta" href={api.capturaPrototipo(proto.id, p.imagen)} target="_blank" rel="noreferrer">
                  <img src={api.capturaPrototipo(proto.id, p.imagen)} alt={p.ruta} loading="lazy" />
                  <span>{p.ruta}</span>
                </a>
              ))}
            </div>
          )}
        </>
      )}

      {proto && (
        <>
          <Campo etiqueta="¿Qué pantalla quiere ver?" ancho
            ayuda="Ej.: «Arma la Consulta de Facturas del Portal Público con su ventana Detalle» o «agrega el filtro por Estado».">
            <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={3} />
          </Campo>
          {motor.vista}
          {trabajo && trabajo.estado === "en_curso" && (
            <p className="estado-trabajo"><span className="girando" /> {trabajo.detalle || "En cola"}</p>
          )}
          {trabajo?.estado === "error" && <p className="aviso-error">{trabajo.error}</p>}
          <button type="button" className="boton primario grande" disabled={!puedeEnviar} onClick={enviar}>
            {ocupado ? <><span className="girando claro" /> Procesando…</> : <><Icono n="spark" size={18} /> Generar versión {proto.versiones.length + 1}</>}
          </button>
          {proto.modo === "documento" && !sinMaquetas && !elegidas.length && <p className="falta">Elija al menos una maqueta.</p>}

          {proto.versiones.length > 0 && version != null && (
            <>
              <div className="seccion-cab">
                <h3>Versiones</h3>
                <div className="chips-version">
                  {proto.versiones.map((v) => (
                    <button key={v} type="button" className={v === version ? "activo" : ""} onClick={() => setVersion(v)}>v{v}</button>
                  ))}
                </div>
              </div>
              <iframe className="vista-prototipo" title={`Prototipo v${version}`} sandbox="allow-scripts" src={api.versionPrototipo(proto.id, version)} />
              <div className="acciones-maquetas">
                <a className="boton" href={api.versionPrototipo(proto.id, version)} target="_blank" rel="noreferrer"><Icono n="eye" size={15} /> Abrir</a>
                <button type="button" className="boton" onClick={adjuntar}><Icono n="doc" size={15} /> Adjuntar al RFD</button>
              </div>
            </>
          )}
          {proto.chat.length > 0 && (
            <ol className="chat-proto">
              {proto.chat.slice(-6).map((m, i) => (
                <li key={i} className={m.rol}><b>{m.rol === "usuario" ? "Usted" : `IA${m.version ? ` · v${m.version}` : ""}`}</b> {m.texto}</li>
              ))}
            </ol>
          )}
        </>
      )}
      {aviso && <p className="aviso-ok">{aviso}</p>}
      {error && <p className="aviso-error">{error}</p>}
    </>
  );
}
