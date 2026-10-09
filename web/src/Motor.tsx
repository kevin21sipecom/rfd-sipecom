import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type CliInfo, type ListaModelos, type Proveedor } from "./api";
import { Icono } from "./components";

const NIVELES: Record<string, string> = {
  minimal: "Mínimo", low: "Bajo", medium: "Medio", high: "Alto", xhigh: "Muy alto", max: "Máximo",
};
const OTRO = "__otro__";
const CLAVE = "rfd.motor";

export interface Motor {
  proveedor: Proveedor;
  modelo: string;
  esfuerzo: string;
  listo: boolean;
  vista: ReactNode;
  /** Campos del motor para un FormData de generación o mejora. */
  agregar: (f: FormData) => void;
}

interface Preferencias { cli: Proveedor; modelos: Partial<Record<Proveedor, string>>; esfuerzo: Partial<Record<Proveedor, string>> }

function leer(): Preferencias {
  try {
    const p = JSON.parse(localStorage.getItem(CLAVE) ?? "") as Preferencias;
    if (p && p.cli) return { cli: p.cli, modelos: p.modelos ?? {}, esfuerzo: p.esfuerzo ?? {} };
  } catch { /* sin preferencias guardadas */ }
  return { cli: "claude", modelos: {}, esfuerzo: {} };
}

function guardar(p: Preferencias) {
  try { localStorage.setItem(CLAVE, JSON.stringify(p)); } catch { /* almacenamiento no disponible */ }
}

/** Selección de CLI, modelo y esfuerzo, compartida por Generar y Mejorar. Recuerda la última elección por CLI. */
export function useMotor(clis: CliInfo[]): Motor {
  const [pref, setPref] = useState<Preferencias>(leer);
  const proveedor = pref.cli;
  const [modelos, setModelos] = useState<ListaModelos | null>(null);
  const [otro, setOtro] = useState(false);
  const [refrescando, setRefrescando] = useState(false);

  const actualizar = (cambio: Partial<Preferencias>) => setPref((p) => { const n = { ...p, ...cambio }; guardar(n); return n; });
  const modelo = pref.modelos[proveedor] ?? "";
  const esfuerzo = pref.esfuerzo[proveedor] ?? "";
  const setModelo = (m: string) => actualizar({ modelos: { ...pref.modelos, [proveedor]: m } });
  const setEsfuerzo = (e: string) => actualizar({ esfuerzo: { ...pref.esfuerzo, [proveedor]: e } });

  const cargar = (refrescar = false) => {
    if (!refrescar) setModelos(null);
    setRefrescando(refrescar);
    api.modelos(proveedor, refrescar).then((m) => {
      setModelos(m);
      setPref((p) => {
        const actual = p.modelos[proveedor];
        if (actual && (m.modelos.some((o) => o.id === actual) || !m.modelos.length)) return p;
        const n = { ...p, modelos: { ...p.modelos, [proveedor]: m.defecto } };
        guardar(n);
        return n;
      });
    }).catch(() => setModelos({ disponible: false, defecto: "", modelos: [], detalle: "No se pudo consultar el catálogo." }))
      .finally(() => setRefrescando(false));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setOtro(false); cargar(); }, [proveedor]);

  const opcion = modelos?.modelos.find((m) => m.id === modelo);
  const enLista = !!opcion;
  const personalizado = otro || (!!modelos && !!modelo && !enLista);
  const niveles = useMemo(() => (opcion?.niveles?.length ? opcion.niveles : []), [opcion]);
  useEffect(() => {
    if (esfuerzo && niveles.length && !niveles.includes(esfuerzo)) setEsfuerzo("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [niveles]);

  const info = clis.find((c) => c.id === proveedor) ?? modelos?.cli;
  const instalada = (c: CliInfo) => c.ruta !== null && c.ruta !== undefined;

  const vista = (
    <div className="motor">
      <div className="motor-fila">
        <label className="motor-campo">
          <span className="campo-etiqueta">CLI</span>
          <span className="select-envoltura">
            <select value={proveedor} onChange={(e) => actualizar({ cli: e.target.value as Proveedor })}>
              {(clis.length ? clis : [{ id: proveedor, nombre: proveedor } as CliInfo]).map((c) => (
                <option key={c.id} value={c.id}>{c.nombre}{c.proveedor ? ` · ${c.proveedor}` : ""}{clis.length && !instalada(c) ? " (no instalada)" : ""}</option>
              ))}
            </select>
          </span>
        </label>
        <span className={`motor-estado ${!modelos ? "cargando" : modelos.disponible ? "ok" : "no"}`}
          title={modelos?.disponible ? "Lista" : modelos?.detalle ?? "Consultando"}>
          <i />{!modelos ? "Consultando" : modelos.disponible ? `${modelos.modelos.length} modelo${modelos.modelos.length === 1 ? "" : "s"}` : "No disponible"}
        </span>
      </div>
      <p className="motor-ayuda">
        Sesión local de la CLI · modelos = listado vivo de esa CLI.
        {info?.reglas && <><br /><span title="Cómo se aísla de sus reglas propias">{info.reglas}</span></>}
      </p>

      <label className="motor-campo">
        <span className="campo-etiqueta motor-etiqueta">
          Modelo
          <button type="button" className="boton-icono mini" title="Volver a consultar el catálogo" disabled={!modelos || refrescando}
            onClick={() => cargar(true)}>
            {refrescando ? <span className="girando" /> : <Icono n="refresh" size={14} />}
          </button>
        </span>
        <span className="select-envoltura">
          <select value={personalizado ? OTRO : modelo} disabled={!modelos?.disponible && !personalizado}
            onChange={(e) => { if (e.target.value === OTRO) { setOtro(true); setModelo(""); } else { setOtro(false); setModelo(e.target.value); } }}>
            {!modelos && <option value="">Consultando modelos…</option>}
            {modelos && !modelos.modelos.length && !personalizado && <option value="">Sin modelos</option>}
            {modelos?.modelos.map((m) => (
              <option key={m.id} value={m.id}>{m.nombre === m.id ? m.id : `${m.nombre} (${m.id})`}{m.etiqueta ? ` — ${m.etiqueta}` : ""}</option>
            ))}
            <option value={OTRO}>Otro modelo…</option>
          </select>
        </span>
        {personalizado && (
          <input className="motor-otro" autoFocus value={modelo} onChange={(e) => setModelo(e.target.value.trim())}
            placeholder={proveedor === "opencode" ? "proveedor/modelo" : "ID o alias del modelo"} spellCheck={false} />
        )}
        {opcion?.detalle && <small className="motor-detalle">{opcion.detalle}</small>}
      </label>

      <label className="motor-campo">
        <span className="campo-etiqueta">{proveedor === "opencode" ? "Variante (esfuerzo)" : "Esfuerzo"}</span>
        <span className="select-envoltura">
          <select value={esfuerzo} onChange={(e) => setEsfuerzo(e.target.value)} disabled={!niveles.length && !personalizado}>
            <option value="">{opcion?.nivel_defecto ? `Por defecto (${NIVELES[opcion.nivel_defecto] ?? opcion.nivel_defecto})` : "Por defecto del modelo"}</option>
            {(personalizado && !niveles.length ? ["low", "medium", "high"] : niveles).map((n) => (
              <option key={n} value={n}>{NIVELES[n] ? `${NIVELES[n]} (${n})` : n}</option>
            ))}
          </select>
        </span>
      </label>

      {modelos && !modelos.disponible && <p className="aviso-error">{modelos.detalle ?? "La CLI no responde."}</p>}
      <div className="modelo-elegido">
        Se usará <code>{proveedor} · {modelo || "modelo por defecto"}{esfuerzo ? ` · ${esfuerzo}` : ""}</code>
        {info?.costo && <span className="tenue"> · informa costo en USD</span>}
      </div>
    </div>
  );

  return {
    proveedor, modelo, esfuerzo, vista,
    listo: !!modelos?.disponible && (!!modelo || proveedor !== "opencode"),
    agregar: (f) => {
      f.append("proveedor", proveedor);
      f.append("modelo", modelo);
      f.append("esfuerzo", esfuerzo);
    },
  };
}
