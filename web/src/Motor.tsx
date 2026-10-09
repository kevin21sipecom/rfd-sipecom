import { useEffect, useState, type ReactNode } from "react";
import { api, type ListaModelos, type Proveedor } from "./api";
import { Campo, Segmentado, SelectorModelo } from "./components";

const NIVELES: Record<string, string> = { low: "Bajo", medium: "Medio", high: "Alto", xhigh: "Muy alto", max: "Máximo" };

export interface Motor {
  proveedor: Proveedor;
  modelo: string;
  esfuerzo: string;
  listo: boolean;
  vista: ReactNode;
  /** Campos del motor para un FormData de generación o mejora. */
  agregar: (f: FormData) => void;
}

/** Estado y selector del motor (proveedor, modelo y nivel de razonamiento), compartido por Generar y Mejorar. */
export function useMotor(): Motor {
  const [proveedor, setProveedor] = useState<Proveedor>("claude");
  const [modelos, setModelos] = useState<ListaModelos | null>(null);
  const [modelo, setModelo] = useState("claude-sonnet-5-5");
  const [esfuerzo, setEsfuerzo] = useState("");

  useEffect(() => {
    setModelos(null);
    api.modelos(proveedor).then((m) => {
      setModelos(m);
      setModelo((actual) => (m.modelos.some((o) => o.id === actual) ? actual : m.defecto));
    }).catch(() => setModelos({ disponible: false, defecto: "", modelos: [] }));
  }, [proveedor]);

  const opcion = modelos?.modelos.find((m) => m.id === modelo);
  const niveles = opcion?.niveles ?? [];
  useEffect(() => {
    setEsfuerzo((actual) => (niveles.includes(actual) ? actual : opcion?.nivel_defecto ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelo, modelos]);

  const vista = (
    <>
      <Segmentado valor={proveedor} onCambio={setProveedor} opciones={[
        { valor: "claude", etiqueta: "Claude", detalle: "CLI" },
        { valor: "codex", etiqueta: "Codex", detalle: "CLI" },
        { valor: "ollama", etiqueta: "Ollama", detalle: "local" },
        { valor: "lmstudio", etiqueta: "LM Studio", detalle: "local" },
      ]} />
      <SelectorModelo opciones={modelos?.modelos ?? []} valor={modelo} onCambio={setModelo} cargando={!modelos} />
      {proveedor === "codex" && niveles.length > 0 && (
        <Campo etiqueta="Nivel de razonamiento" ayuda="Más alto: análisis más profundo, más lento y con más uso de la cuenta." ancho>
          <Segmentado valor={esfuerzo} onCambio={setEsfuerzo}
            opciones={niveles.map((n) => ({ valor: n, etiqueta: NIVELES[n] ?? n, detalle: n === opcion?.nivel_defecto ? "defecto" : undefined }))} />
        </Campo>
      )}
      <div className="modelo-elegido">Se usará <code>{modelo || "modelo por defecto"}{proveedor === "codex" && esfuerzo ? ` · ${esfuerzo}` : ""}</code></div>
      {modelos && !modelos.disponible && (
        <p className="aviso-error">{proveedor === "claude" ? "Claude CLI no está en PATH." : modelos.detalle ?? "El proveedor no responde."}</p>
      )}
    </>
  );

  return {
    proveedor, modelo, esfuerzo, vista,
    listo: !!modelos?.disponible && (!!modelo || proveedor === "codex"),
    agregar: (f) => {
      f.append("proveedor", proveedor);
      f.append("modelo", modelo);
      if (proveedor === "codex") f.append("esfuerzo", esfuerzo);
    },
  };
}
