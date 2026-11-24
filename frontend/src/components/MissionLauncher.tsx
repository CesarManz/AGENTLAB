import { useState } from "react";
import { ChevronDown, Lightbulb, Play, Sparkles, GitBranch, UserCheck } from "lucide-react";
import type { AgentInfoDTO } from "../api";
import { AGENT_INFO } from "../labels";

type Mode = "auto" | "single" | "pipeline";

interface MissionLauncherProps {
  mode: Mode;
  setMode: (m: Mode) => void;
  agents: AgentInfoDTO[];
  agentId: string;
  setAgentId: (id: string) => void;
  workspacePath: string;
  setWorkspacePath: (p: string) => void;
  maxBudget: number;
  setMaxBudget: (b: number) => void;
  useKnowledgeGraph: boolean;
  setUseKnowledgeGraph: (v: boolean) => void;
  prompt: string;
  setPrompt: (p: string) => void;
  isLaunching: boolean;
  isConnected: boolean;
  onLaunch: (customPrompt?: string, customMode?: Mode) => void;
}

const EXAMPLES = [
  {
    label: "📝 Resumir el proyecto",
    prompt: "Analiza los archivos existentes en el workspace y genera un resumen en 'RESUMEN.md'.",
  },
  {
    label: "🧮 Crear una calculadora con pruebas",
    prompt: "Crea 'calc.py' con operaciones básicas y su suite 'test_calc.py', luego ejecuta pytest.",
  },
  {
    label: "✉️ Validar emails y fechas",
    prompt: "Crea un módulo 'utils.py' con validación de emails y formateo de fechas ISO.",
  },
  {
    label: "🛡️ Revisar seguridad",
    prompt: "Audita el código del workspace en busca de errores y problemas de seguridad, y explica lo encontrado.",
  },
];

const MODES: { id: Mode; title: string; desc: string; icon: typeof Sparkles; recommended?: boolean }[] = [
  {
    id: "auto",
    title: "Automático",
    desc: "La IA decide qué agentes participan y en qué orden.",
    icon: Sparkles,
    recommended: true,
  },
  {
    id: "pipeline",
    title: "En equipo",
    desc: "Primero el Explorador revisa, después el Programador hace los cambios.",
    icon: GitBranch,
  },
  {
    id: "single",
    title: "Un solo agente",
    desc: "Elegís un agente y él hace todo el trabajo.",
    icon: UserCheck,
  },
];

function StepTitle({ n, title, hint }: { n: number; title: string; hint?: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="w-7 h-7 shrink-0 rounded-full bg-sage-50 border border-sage-100 text-sage-700 text-xs font-semibold flex items-center justify-center">
        {n}
      </span>
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">{title}</h2>
        {hint && <p className="text-xs text-ink-500 mt-0.5">{hint}</p>}
      </div>
    </div>
  );
}

export function MissionLauncher({
  mode,
  setMode,
  agents,
  agentId,
  setAgentId,
  workspacePath,
  setWorkspacePath,
  maxBudget,
  setMaxBudget,
  useKnowledgeGraph,
  setUseKnowledgeGraph,
  prompt,
  setPrompt,
  isLaunching,
  isConnected,
  onLaunch,
}: MissionLauncherProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
      {/* Encabezado */}
      <header className="space-y-2">
        <h1 className="font-serif text-3xl md:text-4xl text-ink-900 tracking-tight">
          ¿En qué te ayudamos hoy?
        </h1>
        <p className="text-sm text-ink-500 leading-relaxed max-w-xl">
          Escribí lo que necesitás y un equipo de agentes de IA lo hará por vos.
          Antes de cambiar cualquier archivo, <strong className="text-ink-700">siempre te pedirán permiso</strong>.
        </p>
      </header>

      {/* Cómo funciona */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          { n: "1", t: "Describí la tarea", d: "Con tus palabras, como si se lo pidieras a una persona." },
          { n: "2", t: "Aprobá los cambios", d: "Te mostramos qué van a modificar antes de hacerlo." },
          { n: "3", t: "Mirá el resultado", d: "Revisá los archivos y el resumen final." },
        ].map((s) => (
          <div key={s.n} className="rounded-2xl bg-cream-50/70 border border-cream-200 p-4">
            <div className="font-serif text-2xl text-clay-500 leading-none">{s.n}</div>
            <div className="mt-2 text-sm font-semibold text-ink-900">{s.t}</div>
            <div className="mt-1 text-xs text-ink-500 leading-relaxed">{s.d}</div>
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onLaunch();
        }}
        className="card p-6 md:p-8 space-y-8"
      >
        {/* Paso 1 */}
        <section className="space-y-3">
          <StepTitle n={1} title="¿Qué querés que hagan?" hint="Sé lo más claro posible: qué archivo, qué debe hacer, etc." />
          <textarea
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Ej: Creá un archivo 'saludo.py' con una función que diga hola…"
            className="input-soft leading-relaxed resize-none"
            required
          />
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs text-ink-500">
              <Lightbulb className="w-3.5 h-3.5 text-clay-500" />
              ¿Sin ideas? Tocá un ejemplo:
            </div>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.label}
                  type="button"
                  onClick={() => setPrompt(ex.prompt)}
                  className={`text-xs px-3 py-1.5 rounded-full border transition cursor-pointer ${
                    prompt === ex.prompt
                      ? "bg-sage-50 border-sage-500/50 text-sage-700"
                      : "bg-white border-cream-300 text-ink-700 hover:bg-cream-100"
                  }`}
                >
                  {ex.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Paso 2 */}
        <section className="space-y-3">
          <StepTitle n={2} title="¿Cómo querés que trabajen?" hint="Si no estás seguro, dejá “Automático”." />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {MODES.map((item) => {
              const Icon = item.icon;
              const selected = mode === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setMode(item.id)}
                  className={`relative text-left p-4 rounded-2xl border-2 transition cursor-pointer ${
                    selected
                      ? "bg-sage-50 border-sage-500"
                      : "bg-white border-cream-200 hover:border-cream-300"
                  }`}
                >
                  {item.recommended && (
                    <span className="absolute -top-2.5 right-3 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-clay-500 text-white">
                      Recomendado
                    </span>
                  )}
                  <div className="flex items-center gap-2">
                    <Icon className={`w-4 h-4 ${selected ? "text-sage-600" : "text-ink-300"}`} />
                    <span className="text-sm font-semibold text-ink-900">{item.title}</span>
                  </div>
                  <p className="text-xs text-ink-500 mt-1.5 leading-relaxed">{item.desc}</p>
                </button>
              );
            })}
          </div>

          {mode === "single" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 pt-1">
              {(agents.length > 0 ? agents.map((a) => a.id) : ["programador", "explorador", "revisor"]).map((id) => {
                const fromApi = agents.find((a) => a.id === id);
                const info = AGENT_INFO[id] ?? {
                  name: fromApi?.name ?? id,
                  emoji: "🤖",
                  desc: fromApi?.role ?? "",
                };
                const selected = agentId === id;
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setAgentId(id)}
                    className={`text-left p-3 rounded-xl border transition cursor-pointer ${
                      selected ? "bg-white border-sage-500 ring-4 ring-sage-50" : "bg-white border-cream-200 hover:border-cream-300"
                    }`}
                  >
                    <div className="text-sm font-medium text-ink-900">
                      {info.emoji} {info.name}
                    </div>
                    <div className="text-[11px] text-ink-500 mt-0.5">{info.desc}</div>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {/* Opciones avanzadas */}
        <section className="rounded-2xl border border-cream-200 bg-cream-100/50">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="w-full flex items-center justify-between px-4 py-3 text-sm text-ink-700 cursor-pointer"
          >
            <span>
              <span className="font-medium">Opciones avanzadas</span>
              <span className="text-ink-500 text-xs ml-2">(opcional)</span>
            </span>
            <ChevronDown className={`w-4 h-4 transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
          </button>
          {showAdvanced && (
            <div className="px-4 pb-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label className="space-y-1.5 block">
                <span className="text-xs font-medium text-ink-700">Carpeta de trabajo</span>
                <input
                  type="text"
                  value={workspacePath}
                  onChange={(e) => setWorkspacePath(e.target.value)}
                  className="input-soft font-mono text-xs"
                />
                <span className="text-[11px] text-ink-500 block">Dónde los agentes leen y guardan archivos.</span>
              </label>
              <label className="space-y-1.5 block">
                <span className="text-xs font-medium text-ink-700">Límite de consumo (tokens)</span>
                <input
                  type="number"
                  min={1000}
                  step={1000}
                  value={maxBudget}
                  onChange={(e) => setMaxBudget(Number(e.target.value) || 20000)}
                  className="input-soft font-mono text-xs"
                />
                <span className="text-[11px] text-ink-500 block">Evita gastar de más. 40.000 alcanza para la mayoría.</span>
              </label>
              <div className="sm:col-span-2 flex items-center justify-between gap-4 rounded-xl bg-white border border-cream-200 px-4 py-3">
                <div>
                  <div className="text-xs font-medium text-ink-700">Mapa del código</div>
                  <div className="text-[11px] text-ink-500">Ayuda a los agentes a entender proyectos grandes más rápido.</div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={useKnowledgeGraph}
                  onClick={() => setUseKnowledgeGraph(!useKnowledgeGraph)}
                  className={`relative w-11 h-6 rounded-full transition cursor-pointer shrink-0 ${
                    useKnowledgeGraph ? "bg-sage-500" : "bg-cream-300"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
                      useKnowledgeGraph ? "translate-x-5" : ""
                    }`}
                  />
                </button>
              </div>
            </div>
          )}
        </section>

        {/* Acción */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-2">
          <span className="text-xs text-ink-500 flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${isConnected ? "bg-sage-500" : "bg-rose-soft"}`} />
            {isConnected ? "Todo listo para empezar" : "El servidor no responde. ¿Lo iniciaste?"}
          </span>
          <button
            type="submit"
            disabled={isLaunching || !isConnected || !prompt.trim()}
            className="btn-primary w-full sm:w-auto"
          >
            <Play className="w-4 h-4" />
            {isLaunching ? "Empezando…" : "Comenzar tarea"}
          </button>
        </div>
      </form>
    </div>
  );
}
