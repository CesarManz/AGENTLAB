// Textos en lenguaje simple para que cualquier persona entienda qué está pasando.

export const AGENT_INFO: Record<string, { name: string; emoji: string; desc: string }> = {
  explorador: {
    name: "Explorador",
    emoji: "🔍",
    desc: "Revisa los archivos y entiende el proyecto.",
  },
  programador: {
    name: "Programador",
    emoji: "💻",
    desc: "Escribe y modifica el código.",
  },
  revisor: {
    name: "Revisor",
    emoji: "🛡️",
    desc: "Busca errores y problemas de seguridad.",
  },
  arquitecto: {
    name: "Arquitecto",
    emoji: "📐",
    desc: "Diseña la estructura del proyecto.",
  },
  tester: {
    name: "Tester",
    emoji: "🧪",
    desc: "Escribe y ejecuta pruebas automáticas.",
  },
  refactorizador: {
    name: "Refactorizador",
    emoji: "🧹",
    desc: "Ordena y limpia el código existente.",
  },
  documentador: {
    name: "Documentador",
    emoji: "📝",
    desc: "Escribe guías y documentación.",
  },
  analista: {
    name: "Analista",
    emoji: "🔎",
    desc: "Investiga y define qué hay que hacer.",
  },
  planner: {
    name: "Planificador",
    emoji: "🧭",
    desc: "Decide qué agente hace cada parte.",
  },
};

export function agentLabel(id: string) {
  return AGENT_INFO[id] ?? { name: id, emoji: "🤖", desc: "" };
}

export type Tone = "sage" | "clay" | "rose" | "ink" | "sky";

export const STATUS_INFO: Record<string, { label: string; tone: Tone; hint: string }> = {
  pending: { label: "En espera", tone: "ink", hint: "La tarea todavía no empezó." },
  queued: { label: "En cola", tone: "ink", hint: "Esperando su turno." },
  running: { label: "Trabajando", tone: "sky", hint: "Los agentes están trabajando en tu tarea." },
  awaiting_approval: {
    label: "Necesita tu permiso",
    tone: "clay",
    hint: "Un agente quiere hacer un cambio y espera que lo apruebes.",
  },
  interrupted: {
    label: "En pausa",
    tone: "clay",
    hint: "La tarea se detuvo (por ejemplo, al reiniciar el servidor). Podés continuarla.",
  },
  completed: { label: "Terminada", tone: "sage", hint: "¡Listo! La tarea se completó." },
  failed: { label: "Con error", tone: "rose", hint: "Algo salió mal. Podés intentarlo de nuevo." },
  cancelled: { label: "Cancelada", tone: "ink", hint: "La tarea fue cancelada." },
};

export function statusInfo(status: string) {
  return STATUS_INFO[status] ?? { label: status, tone: "ink" as Tone, hint: "" };
}

export const TONE_CLASSES: Record<Tone, string> = {
  sage: "bg-sage-50 text-sage-700 border-sage-100",
  clay: "bg-clay-50 text-clay-700 border-clay-100",
  rose: "bg-[#fbeceb] text-rose-soft border-[#f2d3d0]",
  ink: "bg-cream-200 text-ink-700 border-cream-300",
  sky: "bg-[#eaf1f4] text-[#3f6c80] border-[#d3e3ea]",
};

export const TONE_DOT: Record<Tone, string> = {
  sage: "bg-sage-500",
  clay: "bg-clay-500",
  rose: "bg-rose-soft",
  ink: "bg-ink-300",
  sky: "bg-[#5a8ea5]",
};

export const EVENT_LABELS: Record<string, string> = {
  WS_CONNECTED: "Conectado en vivo",
  SESSION_STARTED: "La tarea comenzó",
  SESSION_COMPLETED: "La tarea terminó",
  SESSION_FAILED: "La tarea falló",
  RUN_STARTED: "Un agente empezó a trabajar",
  STEP_COMPLETED: "Paso completado",
  TOOL_CALLED: "Un agente usó una herramienta",
  APPROVAL_REQUIRED: "Se pidió tu permiso",
  APPROVAL_RESOLVED: "Respondiste el permiso",
  FILE_MODIFIED: "Se modificó un archivo",
  TOKEN_RECORDED: "Consumo registrado",
  RUN_COMPLETED: "Un agente terminó su parte",
  RUN_FAILED: "Un agente tuvo un problema",
  PONG: "Conexión activa",
};

export const TOOL_LABELS: Record<string, string> = {
  list_files: "ver la lista de archivos",
  read_file: "leer un archivo",
  write_file: "crear o reemplazar un archivo",
  edit_file: "editar una parte de un archivo",
  run_pytest: "ejecutar las pruebas automáticas",
  query_code_graph: "consultar el mapa del código",
  git_status: "ver el estado de Git",
  git_diff: "ver los cambios en Git",
  read_blackboard: "leer las notas compartidas",
  write_blackboard: "guardar una nota compartida",
};

export function describeEvent(ev: { event_type: string; payload?: Record<string, unknown> }) {
  const p = ev.payload ?? {};
  const agent = typeof p.agent_id === "string" ? agentLabel(p.agent_id).name : null;
  const tool = typeof p.tool_name === "string" ? TOOL_LABELS[p.tool_name] ?? p.tool_name : null;

  switch (ev.event_type) {
    case "RUN_STARTED":
      return agent ? `${agent} empezó a trabajar` : EVENT_LABELS.RUN_STARTED;
    case "TOOL_CALLED":
      return tool ? `Se usó: ${tool}${p.status === "error" ? " (con error)" : ""}` : EVENT_LABELS.TOOL_CALLED;
    case "APPROVAL_REQUIRED":
      return tool ? `Pide permiso para ${tool}` : EVENT_LABELS.APPROVAL_REQUIRED;
    case "APPROVAL_RESOLVED":
      return p.approved ? "Aprobaste el cambio" : "Rechazaste el cambio";
    case "STEP_COMPLETED":
      return typeof p.step === "number" ? `Paso ${p.step} completado` : EVENT_LABELS.STEP_COMPLETED;
    case "TOKEN_RECORDED":
      return typeof p.total_tokens === "number"
        ? `Se usaron ${p.total_tokens.toLocaleString()} tokens`
        : EVENT_LABELS.TOKEN_RECORDED;
    case "RUN_FAILED":
      return `Problema: ${String(p.error ?? "error desconocido")}`;
    default:
      return EVENT_LABELS[ev.event_type] ?? ev.event_type;
  }
}
