import { Bot, FolderOpen, GitBranch, Play, Sparkles, UserCheck } from "lucide-react";

interface MissionLauncherProps {
  mode: "auto" | "single" | "pipeline";
  setMode: (m: "auto" | "single" | "pipeline") => void;
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
  onLaunch: (customPrompt?: string, customMode?: "auto" | "single" | "pipeline") => void;
}

const TEMPLATES = [
  {
    title: "Auditoría y Resumen del Proyecto",
    tag: "Pipeline • 2 Agentes",
    desc: "Inspecciona los archivos del workspace y genera un informe técnico en RESUMEN.md.",
    prompt: "Analiza los archivos existentes en el workspace y genera un resumen en 'RESUMEN.md'.",
    mode: "pipeline" as const,
  },
  {
    title: "Módulo Python con Validaciones",
    tag: "Auto-Plan IA",
    desc: "Crea funciones utilitarias limpias y solicita aprobación humana antes de escribir en disco.",
    prompt: "Crea un módulo 'utils.py' con validación de emails y formateo de fechas ISO.",
    mode: "auto" as const,
  },
  {
    title: "Crear y Verificar con Pytest",
    tag: "Auto-Plan IA",
    desc: "Implementa código, escribe pruebas unitarias y ejecuta pytest en entorno restringido.",
    prompt: "Crea 'calc.py' con operaciones básicas y su suite 'test_calc.py', luego ejecuta pytest.",
    mode: "auto" as const,
  },
];

export function MissionLauncher({
  mode,
  setMode,
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
  return (
    <div className="max-w-4xl mx-auto p-6 md:p-8 space-y-8">
      <div className="space-y-1.5">
        <h1 className="text-xl font-semibold text-white tracking-tight">
          Nueva Misión de Agentes
        </h1>
        <p className="text-sm text-zinc-400">
          Define qué quieres construir o analizar. Cada misión se ejecuta en una rama Git aislada y pide tu aprobación antes de modificar archivos.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onLaunch();
        }}
        className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-6 space-y-6 shadow-xl"
      >
        {/* Selector de Modo con tarjetas explicativas */}
        <div className="space-y-2.5">
          <label className="block text-xs font-medium text-zinc-300">
            1. Estrategia de Orquestación
          </label>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {[
              {
                id: "auto" as const,
                title: "Planificador IA",
                desc: "Divide la tarea dinámicamente entre los agentes adecuados.",
                icon: Sparkles,
              },
              {
                id: "pipeline" as const,
                title: "Pipeline Estándar (2)",
                desc: "Primero Explorador diagnostica, luego Programador ejecuta.",
                icon: GitBranch,
              },
              {
                id: "single" as const,
                title: "Agente Directo",
                desc: "Un solo agente resuelve el objetivo de principio a fin.",
                icon: UserCheck,
              },
            ].map((item) => {
              const Icon = item.icon;
              const selected = mode === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setMode(item.id)}
                  className={`text-left p-3.5 rounded-lg border transition cursor-pointer ${
                    selected
                      ? "bg-indigo-500/12 border-indigo-500/60 text-white"
                      : "bg-[#08090c] border-[#1f222a] text-zinc-400 hover:border-zinc-700"
                  }`}
                >
                  <div className="flex items-center gap-2 text-xs font-semibold">
                    <Icon className={`w-4 h-4 ${selected ? "text-indigo-400" : "text-zinc-500"}`} />
                    <span>{item.title}</span>
                  </div>
                  <p className="text-[11px] text-zinc-500 mt-1.5 leading-relaxed">
                    {item.desc}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        {/* Objetivo */}
        <div className="space-y-2">
          <label className="block text-xs font-medium text-zinc-300">
            2. Instrucción u Objetivo de la Misión
          </label>
          <textarea
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe con claridad qué archivos crear, modificar o analizar..."
            className="w-full rounded-lg bg-[#07080b] border border-[#232732] focus:border-indigo-500 p-3.5 text-sm text-white placeholder:text-zinc-600 focus:outline-none leading-relaxed"
            required
          />
        </div>

        {/* Parámetros del Entorno */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-1">
          <div className="bg-[#08090c] border border-[#1f222a] rounded-lg p-3 space-y-1">
            <span className="text-[11px] text-zinc-500 flex items-center gap-1.5">
              <FolderOpen className="w-3.5 h-3.5 text-emerald-400" />
              Carpeta Workspace
            </span>
            <input
              type="text"
              value={workspacePath}
              onChange={(e) => setWorkspacePath(e.target.value)}
              className="w-full bg-transparent font-mono text-xs text-zinc-200 focus:outline-none"
            />
          </div>

          <div className="bg-[#08090c] border border-[#1f222a] rounded-lg p-3 space-y-1">
            <span className="text-[11px] text-zinc-500">Presupuesto Máx. Tokens</span>
            <input
              type="number"
              min={1000}
              step={1000}
              value={maxBudget}
              onChange={(e) => setMaxBudget(Number(e.target.value) || 20000)}
              className="w-full bg-transparent font-mono text-xs text-zinc-200 focus:outline-none"
            />
          </div>

          {mode === "single" ? (
            <div className="bg-[#08090c] border border-[#1f222a] rounded-lg p-3 space-y-1">
              <span className="text-[11px] text-zinc-500 flex items-center gap-1.5">
                <Bot className="w-3.5 h-3.5 text-cyan-400" />
                Agente Asignado
              </span>
              <select
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="w-full bg-transparent font-mono text-xs text-zinc-200 focus:outline-none"
              >
                <option value="programador" className="bg-[#0c0d10]">programador</option>
                <option value="explorador" className="bg-[#0c0d10]">explorador</option>
              </select>
            </div>
          ) : (
            <div className="bg-[#08090c] border border-[#1f222a] rounded-lg p-3 space-y-1">
              <span className="text-[11px] text-zinc-500">Aislamiento Git</span>
              <div className="font-mono text-xs text-indigo-300">Rama automática</div>
            </div>
          )}

          <button
            type="button"
            onClick={() => setUseKnowledgeGraph(!useKnowledgeGraph)}
            className={`rounded-lg p-3 border text-left transition cursor-pointer ${
              useKnowledgeGraph
                ? "bg-emerald-950/30 border-emerald-500/40"
                : "bg-[#08090c] border-[#1f222a]"
            }`}
          >
            <div className="text-[11px] text-zinc-500">Mapa AST del Código</div>
            <div
              className={`font-mono text-xs mt-1 ${
                useKnowledgeGraph ? "text-emerald-300" : "text-zinc-400"
              }`}
            >
              {useKnowledgeGraph ? "Activado" : "Desactivado"}
            </div>
          </button>
        </div>

        <div className="flex items-center justify-between pt-2 border-t border-[#181b22]">
          <span className="text-xs text-zinc-500">
            {isConnected ? "Motor listo en 127.0.0.1:8000" : "Backend desconectado"}
          </span>
          <button
            type="submit"
            disabled={isLaunching || !isConnected}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-semibold text-white transition cursor-pointer shadow-lg shadow-indigo-950/40"
          >
            <Play className="w-4 h-4" />
            {isLaunching ? "Iniciando misión..." : "Lanzar Misión"}
          </button>
        </div>
      </form>

      {/* Plantillas Rápidas */}
      <div className="space-y-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
          O comienza con una plantilla rápida
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {TEMPLATES.map((tpl) => (
            <button
              key={tpl.title}
              type="button"
              disabled={isLaunching || !isConnected}
              onClick={() => {
                setPrompt(tpl.prompt);
                setMode(tpl.mode);
                onLaunch(tpl.prompt, tpl.mode);
              }}
              className="text-left bg-[#0c0d10] hover:bg-[#111319] border border-[#1f222a] hover:border-indigo-500/40 rounded-xl p-4 space-y-2 transition cursor-pointer"
            >
              <span className="inline-block font-mono text-[10px] px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                {tpl.tag}
              </span>
              <div className="text-sm font-medium text-zinc-100">{tpl.title}</div>
              <p className="text-xs text-zinc-500 leading-relaxed">{tpl.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}