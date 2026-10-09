import { useEffect, useRef, useState, type ReactNode } from "react";

const RUTAS: Record<string, string> = {
  upload: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  x: "M6 6l12 12M18 6 6 18",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  code: "m8 8-4 4 4 4m8-8 4 4-4 4m-6 2 4-12",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  spark: "M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M6 18l2.5-2.5m7-7L18 6",
  check: "m5 12 5 5 9-10",
  alert: "M12 8v5m0 3.5v.5M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  download: "M12 4v12m0 0-4-4m4 4 4-4M4 20h16",
  doc: "M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm7 0v5h5",
  play: "M7 5v14l11-7z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
};

export function Icono({ n, size = 18 }: { n: keyof typeof RUTAS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={RUTAS[n]} />
    </svg>
  );
}

export function Tarjeta({ numero, titulo, ayuda, children, extra }: {
  numero: number; titulo: string; ayuda?: string; children: ReactNode; extra?: ReactNode;
}) {
  return (
    <section className="tarjeta">
      <header className="tarjeta-cab">
        <span className="numero">{numero}</span>
        <div className="tarjeta-titulos">
          <h2>{titulo}</h2>
          {ayuda && <p>{ayuda}</p>}
        </div>
        {extra}
      </header>
      {children}
    </section>
  );
}

const extension = (nombre: string) => nombre.split(".").pop()?.toLowerCase() ?? "";

export function ZonaArchivos({ titulo, descripcion, archivos, aceptar, onCambio }: {
  titulo: string; descripcion: string; archivos: File[]; aceptar: string[]; onCambio: (a: File[]) => void;
}) {
  const entrada = useRef<HTMLInputElement>(null);
  const [encima, setEncima] = useState(false);
  const [aviso, setAviso] = useState("");

  const agregar = (lista: FileList | null) => {
    if (!lista) return;
    const nuevos: File[] = [];
    const rechazados: string[] = [];
    for (const f of Array.from(lista)) {
      const ext = "." + extension(f.name);
      if (ext === ".ppt") rechazados.push(`${f.name}: guárdelo como .pptx`);
      else if (!aceptar.includes(ext)) rechazados.push(`${f.name}: formato no admitido`);
      else if (!archivos.some((a) => a.name.toLowerCase() === f.name.toLowerCase())) nuevos.push(f);
    }
    setAviso(rechazados.join(" · "));
    if (nuevos.length) onCambio([...archivos, ...nuevos]);
  };

  return (
    <div className="zona-bloque">
      <div className="zona-cab">
        <strong>{titulo}{archivos.length > 0 && <small>{archivos.length}</small>}</strong>
        <span>{descripcion}</span>
      </div>
      <div
        className={`zona ${encima ? "encima" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => entrada.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && entrada.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setEncima(true); }}
        onDragLeave={() => setEncima(false)}
        onDrop={(e) => { e.preventDefault(); setEncima(false); agregar(e.dataTransfer.files); }}
      >
        <Icono n="upload" size={22} />
        <span>Arrastre archivos o <u>examine</u></span>
        <small>{aceptar.join(" · ")}</small>
        <input ref={entrada} type="file" multiple hidden accept={[...aceptar, ".ppt"].join(",")}
          onChange={(e) => { agregar(e.target.files); e.target.value = ""; }} />
      </div>
      {aviso && <p className="aviso-error">{aviso}</p>}
      {archivos.length > 0 && (
        <ul className="chips">
          {archivos.map((f) => (
            <li key={f.name} className="chip">
              <span className={`ext ext-${extension(f.name)}`}>{extension(f.name)}</span>
              <span className="chip-nombre" title={f.name}>{f.name}</span>
              <span className="chip-peso">{(f.size / 1024).toFixed(0)} KB</span>
              <button type="button" className="chip-quitar" aria-label={`Quitar ${f.name}`}
                onClick={() => onCambio(archivos.filter((a) => a !== f))}>
                <Icono n="x" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Campo({ etiqueta, children, ayuda, ancho }: {
  etiqueta: string; children: ReactNode; ayuda?: string; ancho?: boolean;
}) {
  return (
    <label className={`campo ${ancho ? "ancho" : ""}`}>
      <span className="campo-etiqueta">{etiqueta}</span>
      {children}
      {ayuda && <span className="campo-ayuda">{ayuda}</span>}
    </label>
  );
}

export function Segmentado<T extends string>({ opciones, valor, onCambio }: {
  opciones: { valor: T; etiqueta: string; detalle?: string }[]; valor: T; onCambio: (v: T) => void;
}) {
  return (
    <div className="segmentado" role="radiogroup">
      {opciones.map((o) => (
        <button key={o.valor} type="button" role="radio" aria-checked={valor === o.valor}
          className={valor === o.valor ? "activo" : ""} onClick={() => onCambio(o.valor)}>
          <span>{o.etiqueta}</span>
          {o.detalle && <small>{o.detalle}</small>}
        </button>
      ))}
    </div>
  );
}

export function Modal({ titulo, subtitulo, onCerrar, children }: {
  titulo: string; subtitulo?: string; onCerrar: () => void; children: ReactNode;
}) {
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && onCerrar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [onCerrar]);
  return (
    <div className="modal-fondo" onClick={onCerrar}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <h3>{titulo}</h3>
            {subtitulo && <p>{subtitulo}</p>}
          </div>
          <button type="button" className="boton-icono" onClick={onCerrar} aria-label="Cerrar"><Icono n="x" /></button>
        </header>
        <div className="modal-cuerpo">{children}</div>
      </div>
    </div>
  );
}
