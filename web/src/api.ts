// Cliente tipado del servidor local (generador_rfd/servidor.py).

export type Proveedor = "claude" | "codex" | "ollama" | "lmstudio";

export interface Entorno {
  claude: string | null;
  codex: string | null;
  codegraph: string | null;
  repomix: string | null;
  plantilla: boolean;
  word: boolean;
  salidas: string;
  extensiones: string[];
  fecha: string;
}

export interface OpcionModelo {
  id: string;
  nombre: string;
  detalle: string;
  etiqueta?: string;
  niveles?: string[];
  nivel_defecto?: string;
}

export interface ListaModelos {
  disponible: boolean;
  defecto: string;
  modelos: OpcionModelo[];
  detalle?: string;
}

export interface Uso {
  modelos: string[];
  costo_usd: number | null;
  llamadas?: number;
  tokens_entrada?: number;
  tokens_salida?: number;
}

export interface Requerimiento {
  id: string;
  nombre: string;
  evidencias: string[];
}

export interface Resultado {
  titulo: string;
  cliente: string;
  codigo: string;
  objetivo: string;
  requerimientos: Requerimiento[];
  pendientes: { pregunta: string; motivo: string }[];
  supuestos: string[];
  hallazgos: { codigo: string; mensaje: string }[];
  revision_md: string;
  carpeta: string;
  archivo: string;
  definiciones: { id: string; titulo: string; descripcion: string; evidencias: string[] }[];
  paginas: number | null;
  pdf: boolean;
  word: string | null;
  calidad: Calidad | null;
  rfd_id?: number;
  version?: string;
  preguntas_cliente?: { id: string; tema: string; contexto: string; pregunta: string; relacion: string[] }[];
  cambios?: Cambio[];
  cuestionario?: boolean;
}

export interface Cambio {
  pregunta: string;
  seccion: string;
  cambio: string;
}

export interface RfdResumen {
  id: number;
  codigo: string;
  cliente: string;
  titulo: string;
  version: string;
  padre_id: number | null;
  creado: string;
  origen: "generado" | "mejorado" | "importado" | "en_avance" | "continuado";
  proveedor: string | null;
  modelo: string | null;
  calidad: number | null;
  preguntas: number;
  abiertas: number;
  respondidas: number;
  mejorado: boolean;
  archivo: string | null;
}

export interface PreguntaGuardada {
  pid: string;
  tema: string;
  contexto: string;
  pregunta: string;
  relacion: string[];
  respuesta: string;
  estado: "abierta" | "respondida" | "pendiente";
  respondida_en: string | null;
}

export interface RfdDetalle extends Omit<RfdResumen, "preguntas" | "abiertas" | "respondidas" | "mejorado" | "archivo" | "calidad"> {
  objetivo: string;
  calidad: Calidad | null;
  requerimientos: { id: string; nombre: string }[];
  definiciones: { id: string; titulo: string; descripcion: string }[];
  cambios: Cambio[];
  historial: { version: string; fecha: string; descripcion: string }[];
  preguntas: PreguntaGuardada[];
  archivos: Record<"docx" | "pdf" | "cuestionario" | "revision", boolean>;
}

export interface Calidad {
  puntaje: number;
  umbral: number;
  rondas: number;
  criterios: { id: string; descripcion: string; ok: boolean; detalle: string }[];
}

export type Paso = "cola" | "base" | "respuestas" | "fuentes" | "analisis" | "codigo" | "modelo" | "calidad" | "word" | "revision" | "listo";

export interface Trabajo {
  id: string;
  tipo?: "mejora" | "preguntas" | "importacion" | "continuacion";
  estado: "en_curso" | "listo" | "error";
  paso: Paso;
  detalle?: string;
  inicio: number;
  fin?: number;
  error?: string;
  proveedor: string;
  modelo: string;
  fuentes?: { id: string; categoria: string; nombre: string; caracteres: number }[];
  uso?: Uso;
  resultado?: Resultado;
}

export interface Regla {
  id: number | null;
  texto: string;
  tipo: "evitar" | "exigir";
  seccion: string;
  patron: string;
  cliente: string;
  activa: boolean;
}

export interface ListaReglas {
  reglas: Regla[];
  secciones: Record<string, string>;
  aplicables: number[];
}

export interface ContextoCodigo {
  nombre: string;
  contenido: string;
  caracteres: number;
}

async function pedir<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let detalle = `${r.status} ${r.statusText}`;
    try {
      const cuerpo = await r.json();
      if (typeof cuerpo.detail === "string") detalle = cuerpo.detail;
      else if (Array.isArray(cuerpo.detail)) detalle = cuerpo.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* respuesta sin JSON */
    }
    throw new Error(detalle);
  }
  return r.json() as Promise<T>;
}

const json = (cuerpo: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cuerpo),
});

export const api = {
  entorno: () => pedir<Entorno>("/api/entorno"),
  modelos: async (p: Proveedor): Promise<ListaModelos> => {
    const r = await pedir<Partial<ListaModelos> & { modelos?: (OpcionModelo | string)[] }>(`/api/modelos?proveedor=${p}`);
    // Tolera un servidor anterior que devolvía sólo nombres.
    const modelos = (r.modelos ?? [])
      .map((m) => (typeof m === "string" ? { id: m, nombre: m, detalle: "" } : m))
      .filter((m) => m.id);
    return { disponible: !!r.disponible, detalle: r.detalle, modelos, defecto: r.defecto || modelos[0]?.id || "" };
  },
  elegirCarpeta: () => pedir<{ ruta: string }>("/api/elegir-carpeta"),
  contextoCodigo: (proyecto: string, enfoque: string) =>
    pedir<ContextoCodigo>("/api/contexto-codigo", json({ proyecto, enfoque })),
  generar: (datos: FormData) => pedir<{ id: string }>("/api/generar", { method: "POST", body: datos }),
  demo: () => pedir<{ id: string }>("/api/demo", { method: "POST" }),
  trabajo: (id: string) => pedir<Trabajo>(`/api/trabajos/${id}`),
  abrir: (id: string, tipo: "carpeta" | "docx" | "pdf") => pedir<{ ok: boolean }>(`/api/trabajos/${id}/abrir?tipo=${tipo}`, { method: "POST" }),
  archivo: (id: string, tipo: "docx" | "json" | "revision" | "pdf" | "analisis" | "cuestionario") => `/api/trabajos/${id}/archivo/${tipo}`,
  rfds: () => pedir<RfdResumen[]>("/api/rfds"),
  rfd: (id: number) => pedir<RfdDetalle>(`/api/rfds/${id}`),
  responder: (id: number, pid: string, respuesta: string) =>
    pedir<{ pid: string; respuesta: string; estado: PreguntaGuardada["estado"] }>(`/api/rfds/${id}/preguntas/${pid}`,
      { ...json({ respuesta }), method: "PUT" }),
  cargarCuestionario: (id: number, archivo: File) => {
    const f = new FormData();
    f.append("archivo", archivo);
    return pedir<{ leidas: number; guardadas: number; preguntas: PreguntaGuardada[] }>(`/api/rfds/${id}/cuestionario`, { method: "POST", body: f });
  },
  mejorar: (id: number, datos: FormData) => pedir<{ id: string }>(`/api/rfds/${id}/mejorar`, { method: "POST", body: datos }),
  importar: (datos: FormData) => pedir<{ id: string }>("/api/rfds/importar", { method: "POST", body: datos }),
  continuar: (id: number, datos: FormData) => pedir<{ id: string }>(`/api/rfds/${id}/continuar`, { method: "POST", body: datos }),
  crearPreguntas: (id: number, datos: FormData) => pedir<{ id: string }>(`/api/rfds/${id}/preguntas`, { method: "POST", body: datos }),
  eliminarRfd: (id: number) => pedir<{ ok: boolean }>(`/api/rfds/${id}`, { method: "DELETE" }),
  abrirRfd: (id: number, tipo: "docx" | "pdf" | "carpeta" | "cuestionario") => pedir<{ ok: boolean }>(`/api/rfds/${id}/abrir?tipo=${tipo}`, { method: "POST" }),
  reglas: (cliente = "") => pedir<ListaReglas>(`/api/reglas?cliente=${encodeURIComponent(cliente)}`),
  guardarRegla: (r: Regla) => r.id == null
    ? pedir<Regla>("/api/reglas", json(r))
    : pedir<Regla>(`/api/reglas/${r.id}`, { ...json(r), method: "PUT" }),
  eliminarRegla: (id: number) => pedir<{ ok: boolean }>(`/api/reglas/${id}`, { method: "DELETE" }),
  archivoRfd: (id: number, tipo: "docx" | "pdf" | "cuestionario" | "revision" | "json") => `/api/rfds/${id}/archivo/${tipo}`,
};
