import { useState } from "react";
import {
  Activity,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  FileText,
  GitBranch,
  Layers,
  Play,
  RotateCcw,
  ShieldAlert,
  Terminal,
  X,
} from "lucide-react";
import type { SessionStateResponse, SystemEventDTO } from "../api";
import { DiffViewer } from "./DiffViewer";

interface LiveMissionMonitorProps {
  sessionState: SessionStateResponse | null;
  events: SystemEventDTO[];
  isResolving: boolean;
  isSafetyBusy: boolean;
  safetyBanner: { kind: "ok" | "warn"; text: string } | null;
  onDecision: (executionId: string, approved: boolean) => void;
  onRollback: () => void;
  onResume: () => void;
  onNewMission: () => void;
  onRetryMission: () => void;
}

const STATUS_LABELS: Record<string, { label: string; style: string }> = {
  completed: {
    label: "Completada",
    style: "text-emerald-300 bg-emerald-500/10 border-emerald-500/30",
  },
  awaiting_approval: {
    label: "Esperando Tu Aprobación",
    style: "text-amber-300 bg-amber-500/15 border-amber-500/40",
  },
  interrupted: {
    label: "Interrumpida (Reanudable)",
    style: "text-amber-300 bg-amber-500/15 border-amber-500/40",
  },
  running: {
    label: "Ejecutando",
    style: "text-cyan-300 bg-cyan-500/10 border-cyan-500/30",
  },
  failed: {
    label: "Con Error",
    style: "text-rose-300 bg-rose-500/10 border-rose-500/30",
  },
};

export function LiveMissionMonitor({
  sessionState,
  events,
  isResolving,
  isSafetyBusy,
  safetyBanner,
  onDecision,
  onRollback,
  onResume,
  onNewMission,
  onRetryMission,
}: LiveMissionMonitorProps) {
  const [inspectorTab, setInspectorTab] = useState<"logs" | "memory">("logs");

  if (!sessionState) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="max-w-md text-center bg-[#0c0d10] border border-[#1f222a] rounded-xl p-8 space-y-4">
          <div className="w-12 h-12 rounded-full bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center mx-auto text-indigo-400">
            <Bot className="w-6 h-6" />
          </div>
          <h2 className="text-base font-semibold text-white">No hay una misión activa seleccionada</h2>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Lanza una nueva misión o selecciona una ejecución anterior desde el historial para ver su progreso y resultados.
          </p>
          <button
            type="button"
            onClick={onNewMission}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white cursor-pointer"
          >
            <Play className="w-3.5 h-3.5" />
            Crear Nueva Misión
          </button>
        </div>
      </div>
    );
  }

  const { session, runs, pending_approvals } = sessionState;
  const gateItem = pending_approvals[0] ?? null;
  const statusInfo = STATUS_LABELS[session.status] ?? {
    label: session.status,
    style: "text-zinc-300 bg-zinc-800/60 border-zinc-700",
  };
  const blackboardEntries = Object.entries(session.blackboard ?? {});
  const touchedCount = session.git_checkpoint?.agent_touched_paths?.length ?? 0;

  return (
    <div className="p-6 max-w-7xl w-full mx-auto space-y-6">
      {/* Cabecera de la Misión + Controles de Seguridad */}
      <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="space-y-1.5 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`font-mono text-[11px] px-2.5 py-0.5 rounded-full border ${statusInfo.style}`}>
              {statusInfo.label}
            </span>
            {session.git_checkpoint?.is_git_repo && session.git_checkpoint.mission_branch && (
              <span className="font-mono text-[11px] px-2.5 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 flex items-center gap-1">
                <GitBranch className="w-3 h-3" />
                {session.git_checkpoint.mission_branch}
              </span>
            )}
            <span className="font-mono text-[11px] text-zinc-500">
              ID #{session.id.slice(0, 8)}
            </span>
          </div>
          <h1 className="text-base font-semibold text-white truncate" title={session.user_prompt}>
            {session.user_prompt}
          </h1>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 shrink-0">
          {session.status === "failed" && (
            <button
              type="button"
              onClick={onRetryMission}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reintentar Misión
            </button>
          )}
          {session.status === "interrupted" && (
            <button
              type="button"
              disabled={isSafetyBusy}
              onClick={onResume}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-medium cursor-pointer"
            >
              <Play className="w-3.5 h-3.5" />
              Reanudar Sesión
            </button>
          )}
          {session.git_checkpoint?.is_git_repo && touchedCount > 0 && (
            <button
              type="button"
              disabled={isSafetyBusy}
              onClick={onRollback}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/15 hover:bg-rose-500/25 border border-rose-500/35 text-rose-300 text-xs font-medium cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Revertir Cambios ({touchedCount})
            </button>
          )}
        </div>
      </div>

      {safetyBanner && (
        <div
          className={`px-4 py-3 rounded-lg border text-xs ${
            safetyBanner.kind === "ok"
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
              : "bg-amber-500/15 border-amber-500/35 text-amber-200"
          }`}
        >
          {safetyBanner.text}
        </div>
      )}

      {/* BANNER PRIORITARIO HITL (solo aparece cuando requiere atención del usuario) */}
      {gateItem && (
        <div className="rounded-xl border-2 border-amber-500/60 bg-[#100e09] p-5 space-y-4 shadow-lg shadow-amber-950/20">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-amber-500/20 flex items-center justify-center text-amber-400">
                <ShieldAlert className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-amber-300">
                  Acción Pendiente de Aprobación Humana
                </h2>
                <p className="text-xs text-zinc-400">
                  El agente solicita ejecutar{" "}
                  <code className="text-amber-200 font-mono">{gateItem.tool_name}</code> (riesgo{" "}
                  {gateItem.risk_level}). Revisa los cambios antes de continuar:
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                type="button"
                disabled={isResolving}
                onClick={() => onDecision(gateItem.id, false)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#16181f] hover:bg-rose-950/60 border border-[#2a2e39] text-rose-300 text-xs font-medium cursor-pointer"
              >
                <X className="w-4 h-4" />
                Rechazar
              </button>
              <button
                type="button"
                disabled={isResolving}
                onClick={() => onDecision(gateItem.id, true)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold cursor-pointer"
              >
                <Check className="w-4 h-4" />
                Aprobar y Ejecutar
              </button>
            </div>
          </div>

          {gateItem.diff_preview ? (
            <DiffViewer diffText={gateItem.diff_preview} />
          ) : (
            <pre className="bg-[#050507] border border-[#1f222a] rounded-lg p-3 font-mono text-[11px] text-cyan-300 overflow-x-auto max-h-48">
              {JSON.stringify(gateItem.arguments, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Cuerpo Principal: Izquierda (Etapas + Resultado) | Derecha (Logs / Memoria) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 space-y-6">
          {/* Flujo de Agentes */}
          <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
                Progreso del Equipo de Agentes
              </h2>
              <span className="font-mono text-[11px] text-zinc-500">
                {runs.length} {runs.length === 1 ? "etapa" : "etapas"}
              </span>
            </div>

            {runs.length === 0 ? (
              <div className="py-8 text-center text-xs text-zinc-500">
                Preparando etapas de ejecución...
              </div>
            ) : (
              <div className="space-y-3">
                {runs.map((run, idx) => {
                  const rStatus = STATUS_LABELS[run.status] ?? {
                    label: run.status,
                    style: "text-zinc-400 bg-zinc-800 border-zinc-700",
                  };
                  return (
                    <div
                      key={run.id}
                      className="rounded-lg bg-[#08090c] border border-[#1c1f27] p-4 flex items-start justify-between gap-4"
                    >
                      <div className="space-y-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[11px] text-indigo-400">
                            Paso {idx + 1}
                          </span>
                          <ArrowRight className="w-3 h-3 text-zinc-600" />
                          <span className="text-sm font-semibold text-white capitalize">
                            {run.agent_id}
                          </span>
                        </div>
                        <p className="text-xs text-zinc-400 line-clamp-2">
                          {run.result_summary || run.task_instruction}
                        </p>
                        {run.error_message && (
                          <div className="mt-2 rounded bg-rose-500/10 border border-rose-500/25 px-2.5 py-1.5 font-mono text-[11px] text-rose-300 break-words">
                            {run.error_message}
                          </div>
                        )}
                      </div>
                      <div className="text-right shrink-0 space-y-1">
                        <span className={`inline-block font-mono text-[10px] px-2 py-0.5 rounded border ${rStatus.style}`}>
                          {rStatus.label}
                        </span>
                        <div className="font-mono text-[10px] text-zinc-500">
                          Turno {run.current_step}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Resultado Final */}
          <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-5 space-y-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-zinc-400">
              <FileText className="w-4 h-4 text-indigo-400" />
              Resultado Final de la Misión
            </div>
            {session.final_output ? (
              <div className="text-sm text-zinc-200 whitespace-pre-wrap bg-[#07080b] border border-[#1a1d24] rounded-lg p-4 leading-relaxed max-h-80 overflow-y-auto">
                {session.final_output}
              </div>
            ) : (
              <div className="text-xs text-zinc-500 bg-[#07080b] border border-[#1a1d24] rounded-lg p-4 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-zinc-600" />
                El resumen final aparecerá aquí cuando los agentes concluyan.
              </div>
            )}
          </div>
        </div>

        {/* Columna Derecha con Pestañas para evitar saturación */}
        <div className="lg:col-span-5 bg-[#0c0d10] border border-[#1f222a] rounded-xl flex flex-col overflow-hidden min-h-[420px]">
          <div className="flex border-b border-[#1f222a] bg-[#08090c]">
            <button
              type="button"
              onClick={() => setInspectorTab("logs")}
              className={`flex-1 py-3 px-4 text-xs font-medium flex items-center justify-center gap-2 border-b-2 transition cursor-pointer ${
                inspectorTab === "logs"
                  ? "border-indigo-500 text-white bg-[#0c0d10]"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <Terminal className="w-3.5 h-3.5 text-cyan-400" />
              Actividad en Vivo ({events.length})
            </button>
            <button
              type="button"
              onClick={() => setInspectorTab("memory")}
              className={`flex-1 py-3 px-4 text-xs font-medium flex items-center justify-center gap-2 border-b-2 transition cursor-pointer ${
                inspectorTab === "memory"
                  ? "border-indigo-500 text-white bg-[#0c0d10]"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <Layers className="w-3.5 h-3.5 text-emerald-400" />
              Memoria Compartida ({blackboardEntries.length})
            </button>
          </div>

          <div className="flex-1 p-4 overflow-y-auto max-h-[540px]">
            {inspectorTab === "logs" ? (
              events.length === 0 ? (
                <div className="text-xs text-zinc-600 text-center py-12">
                  Los eventos en tiempo real se mostrarán aquí durante la ejecución.
                </div>
              ) : (
                <div className="space-y-2 font-mono text-[11px]">
                  {events.map((ev, idx) => (
                    <div
                      key={ev.id || idx}
                      className="p-2.5 rounded-lg bg-[#07080b] border border-[#171a22] flex items-start gap-2"
                    >
                      <Activity className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                      <div className="min-w-0">
                        <div className="text-cyan-400 font-semibold">{ev.event_type}</div>
                        {ev.payload && (
                          <div className="text-zinc-400 break-all mt-0.5">
                            {JSON.stringify(ev.payload)}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )
            ) : blackboardEntries.length === 0 ? (
              <div className="text-xs text-zinc-600 text-center py-12">
                Los agentes aún no han guardado notas en el Blackboard.
              </div>
            ) : (
              <div className="space-y-3">
                {blackboardEntries.map(([k, v]) => (
                  <div
                    key={k}
                    className="rounded-lg bg-[#07080b] border border-[#1a1d24] p-3 space-y-1.5"
                  >
                    <div className="font-mono text-xs text-cyan-400 font-semibold">{k}</div>
                    <div className="text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed">
                      {typeof v === "string" ? v : JSON.stringify(v, null, 2)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}