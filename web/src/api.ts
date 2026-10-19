// Cliente tipado del servidor local (generador_rfd/servidor.py).

export type Proveedor = "claude" | "codex" | "agy" | "grok" | "opencode";

export interface CliInfo {
  id: Proveedor;
  nombre: string;
  proveedor: string;
  reglas: string;
  costo: boolean;
  ruta?: string | null;
}

export interface Entorno {
  clis: CliInfo[];
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
  cli?: CliInfo;
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
  proyecto?: string;
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
  archivos: Record<"docx" | "pdf" | "cuestionario" | "revision" | "prototipo", boolean>;
}

export interface Calidad {
  puntaje: number;
  umbral: number;
  rondas: number;
  criterios: { id: string; descripcion: string; ok: boolean; detalle: string }[];
}

export type Paso = "cola" | "base" | "respuestas" | "fuentes" | "analisis" | "codigo" | "modelo" | "calidad" | "word" | "revision" | "listo";

export interface ImagenMaqueta {
  archivo: string;
  titulo: string;
  contexto: string;
  origen: string;
}

export interface EstadoProceso {
  estado: "detenido" | "iniciando" | "activo" | "error";
  url: string | null;
  log: string[];
  codigo: number | null;
  externo: boolean;
}

export interface MensajeChat {
  rol: "usuario" | "ia";
  texto: string;
  cuando: string;
  version?: number;
}

export type ModoPrototipo = "documento" | "proyecto";

export interface RfdVinculado {
  id: number;
  codigo: string;
  titulo: string;
  version: string;
}

export interface PrototipoResumen {
  id: string;
  modo: ModoPrototipo;
  ruta: string;
  creado: string;
  versiones: number;
  rfd: RfdVinculado | null;
}

export interface PrototipoDetalle extends Omit<PrototipoResumen, "versiones"> {
  chat: MensajeChat[];
  versiones: number[];
  imagenes: ImagenMaqueta[];
  proceso: EstadoProceso;
  captura: { pantallas: { ruta: string; imagen: string; html: string }[] };
}

export interface ComandoDetectado {
  etiqueta: string;
  comando: string[];
  cwd: string;
  url_esperada: string | null;
}

export interface Trabajo {
  id: string;
  tipo?: "mejora" | "preguntas" | "importacion" | "continuacion" | "prototipo" | "captura";
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
  codigo?: string;
  observacion?: string;
  predeterminada?: boolean;
}

export interface ListaReglas {
  reglas: Regla[];
  secciones: Record<string, string>;
  observaciones: Record<string, string>;
  aplicables: number[];
}

export interface ContextoCodigo {
  nombre: string;
  contenido: string;
  caracteres: number;
}

/** Estado del puente con el estimador de horas (generador-tiempos) a través de Engram. */
export interface Integracion {
  engram: boolean;
  engram_url: string;
  estimador_url: string;
  handoff: { version: string; enviado: string } | null;
  estimacion: {
    version: string;
    total_horas_dev: number;
    total_horas_proyecto: number;
    aprobado: boolean;
    url_estimacion: string;
    estimado: string;
  } | null;
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
  modelos: async (p: Proveedor, refrescar = false): Promise<ListaModelos> => {
    const r = await pedir<Partial<ListaModelos> & { modelos?: (OpcionModelo | string)[] }>(`/api/modelos?proveedor=${p}${refrescar ? "&refrescar=true" : ""}`);
    // Tolera un servidor anterior que devolvía sólo nombres.
    const modelos = (r.modelos ?? [])
      .map((m) => (typeof m === "string" ? { id: m, nombre: m, detalle: "" } : m))
      .filter((m) => m.id);
    return { disponible: !!r.disponible, detalle: r.detalle, cli: r.cli, modelos, defecto: r.defecto || modelos[0]?.id || "" };
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
  restaurarRegla: (id: number) => pedir<Regla>(`/api/reglas/${id}/restaurar`, { method: "POST" }),
  eliminarRegla: (id: number) => pedir<{ ok: boolean }>(`/api/reglas/${id}`, { method: "DELETE" }),
  archivoRfd: (id: number, tipo: "docx" | "pdf" | "cuestionario" | "revision" | "json" | "prototipo") => `/api/rfds/${id}/archivo/${tipo}`,
  prototipos: () => pedir<PrototipoResumen[]>("/api/prototipos"),
  prototipo: (id: string) => pedir<PrototipoDetalle>(`/api/prototipos/${id}`),
  crearPrototipo: (modo: ModoPrototipo, rfd_id: number, ruta = "") => pedir<{ id: string }>("/api/prototipos", json({ modo, rfd_id, ruta })),
  subirMaquetas: (id: string, archivos: File[]) => {
    const f = new FormData();
    archivos.forEach((a) => f.append("archivos", a));
    return pedir<{ imagenes: ImagenMaqueta[] }>(`/api/prototipos/${id}/imagenes`, { method: "POST", body: f });
  },
  detectarComandos: (ruta: string) => pedir<{ comandos: ComandoDetectado[] }>(`/api/prototipos/detectar?ruta=${encodeURIComponent(ruta)}`),
  levantar: (id: string, cuerpo: { comando?: string[] | string; url_esperada?: string | null; url?: string }) =>
    pedir<EstadoProceso>(`/api/prototipos/${id}/levantar`, json(cuerpo)),
  detener: (id: string) => pedir<EstadoProceso>(`/api/prototipos/${id}/detener`, { method: "POST" }),
  capturar: (id: string, rutas: string[]) => pedir<{ id: string }>(`/api/prototipos/${id}/capturar`, json({ rutas })),
  mensajePrototipo: (id: string, datos: FormData) => pedir<{ id: string }>(`/api/prototipos/${id}/mensaje`, { method: "POST", body: datos }),
  adjuntarPrototipo: (id: string, version: number) =>
    pedir<{ ok: boolean; version: number; archivo: string; pantallas: number; aviso: string }>(`/api/prototipos/${id}/adjuntar-rfd`, json({ version })),
  imagenPrototipo: (id: string, archivo: string) => `/api/prototipos/${id}/imagenes/${archivo}`,
  capturaPrototipo: (id: string, archivo: string) => `/api/prototipos/${id}/captura/${archivo}`,
  versionPrototipo: (id: string, version: number) => `/api/prototipos/${id}/v/${version}`,
  integracion: (codigo: string) => pedir<Integracion>(`/api/integracion?codigo=${encodeURIComponent(codigo)}`),
  enviarEstimador: (id: number, proyecto = "") =>
    pedir<{ ok: boolean; observacion: number; estimador_url: string }>(`/api/rfds/${id}/enviar-estimador`, json({ proyecto })),
};
