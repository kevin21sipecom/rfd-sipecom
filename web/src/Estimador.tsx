import { useCallback, useEffect, useState } from "react";
import { api, type Integracion } from "./api";
import { Icono } from "./components";

const horas = (h: number) => `${h.toLocaleString("es", { maximumFractionDigits: 1 })} h`;
const momento = (s?: string) => (s ? new Date(s).toLocaleString("es", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

/** Envía el RFD al estimador de horas a través de Engram y muestra la estimación que vuelve. */
export function EnviarEstimador({ rfdId, codigo, version, proyecto = "" }: {
  rfdId: number; codigo: string; version: string; proyecto?: string;
}) {
  const [info, setInfo] = useState<Integracion | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState("");

  const consultar = useCallback(() => api.integracion(codigo).then(setInfo).catch(() => setInfo(null)), [codigo]);
  useEffect(() => {
    consultar();
    const t = setInterval(consultar, 30000);
    return () => clearInterval(t);
  }, [consultar]);

  const enviar = async () => {
    setEnviando(true);
    setError("");
    try {
      await api.enviarEstimador(rfdId, proyecto);
      await consultar();
    } catch (e) { setError((e as Error).message); } finally { setEnviando(false); }
  };

  const enviada = info?.handoff?.version === version;
  const estimacion = info?.estimacion?.version === version ? info.estimacion : null;

  return (
    <div className="puente-estimador">
      <div className="puente-cab">
        <button type="button" className="boton" disabled={enviando} onClick={enviar}
          title="Publica el RFD en Engram para que el estimador de horas lo reciba">
          {enviando ? <><span className="girando" /> Enviando…</> : <><Icono n="send" size={15} /> {enviada ? "Reenviar al estimador" : "Enviar al estimador"}</>}
        </button>
        {info && <a href={info.estimador_url} target="_blank" rel="noreferrer">Abrir estimador</a>}
        {estimacion?.url_estimacion && <a href={estimacion.url_estimacion}>Excel de la estimación</a>}
      </div>
      {info && !info.engram && <small className="puente-estado atencion">Engram no responde en {info.engram_url}; al enviar se intentará iniciarlo.</small>}
      {enviada && !estimacion && <small className="puente-estado">Enviado v{version} el {momento(info!.handoff!.enviado)} · pendiente de estimar</small>}
      {estimacion && (
        <small className={`puente-estado ${estimacion.aprobado ? "ok" : "atencion"}`}>
          Estimado v{version}: <b>{horas(estimacion.total_horas_proyecto)}</b> totales · {horas(estimacion.total_horas_dev)} DEV · {momento(estimacion.estimado)}
        </small>
      )}
      {error && <small className="puente-estado error">{error}</small>}
    </div>
  );
}
