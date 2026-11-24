import { useState } from "react";
import {
  Check,
  ChevronDown,
  GitBranch,
  Play,
  RotateCcw,
  ShieldAlert,
  Square,
  X,
} from "lucide-react";
import type { SessionStateResponse, SystemEventDTO, ToolExecutionDTO } from "../api";
import {
  TONE_CLASSES,
  TONE_DOT,
  TOOL_LABELS,
  agentLabel,
  describeEvent,
  statusInfo,
} from "../labels";
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
  onStopMission: () => void;
}

function explainApproval(item: ToolExecutionDTO) {
  const path = typeof item.arguments?.path === "string" ? item.arguments.path : null;
  switch (item.tool_name) {
    case "write_file":
      return {
        title: path ? `Quiere crear o reemplazar el archivo “${path}”` : "Quiere crear un archivo",
        detail: "Abajo ves exactamente lo que va a escribir. Si existía, se guarda una copia de respaldo.",
      };
    case "edit_file":
      return {
        title: path ? `Quiere editar el archivo “${path}”` : "Quiere editar un archivo",
        detail: "Las líneas verdes se agregan y las rojas se quitan.",
      };
    case "run_pytest":
      return {
        title: "Quiere ejecutar las pruebas automáticas",
        detail: "Corre los tests del proyecto para comprobar que todo funcione. No usa tus claves privadas.",
      };
    default:
      return {
        title: `Quiere ${TOOL_LABELS[item.tool_name] ?? item.tool_name}`,
        detail: "Revisá los detalles antes de decidir.",
      };
  }
}

function Section({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 cursor-pointer"
      >
        <span className="text-sm font-semibold text-ink-900">
          {title}
          {count !== undefined && <span className="ml-2 text-xs font-normal text-ink-500">({count})</span>}
        </span>
        <ChevronDown className={`w-4 h-4 text-ink-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="px-5 pb-5">{children}</div>}
    </div>
  );
}

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
  onStopMission,
}: LiveMissionMonitorProps) {
  if (!sessionState) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 min-h-[70vh]">
        <div className="max-w-sm text-center space-y-4">
          <div className="text-5xl">🌱</div>
          <h2 className="font-serif text-2xl text-ink-900">Todavía no hay ninguna tarea</h2>
          <p className="text-sm text-ink-500 leading-relaxed">
            Cuando crees una tarea, acá vas a ver paso a paso lo que hacen los agentes.
          </p>
          <button type="button" onClick={onNewMission} className="btn-primary">
            <Play className="w-4 h-4" />
            Crear mi primera tarea
          </button>
        </div>
      </div>
    );
  }

  const { session, runs, pending_approvals } = sessionState;
  const gateItem = pending_approvals[0] ?? null;
  const status = statusInfo(session.status);
  const blackboardEntries = Object.entries(session.blackboard ?? {});
  const touchedCount = session.git_checkpoint?.agent_touched_paths?.length ?? 0;
  const visibleEvents = events.filter((e) => e.event_type !== "PONG");
  const isActive = session.status === "running" || session.status === "awaiting_approval";
  const usedPct = Math.min(
    100,
    Math.round(((session.total_tokens_used || 0) / (session.max_budget_tokens || 1)) * 100)
  );

  return (
    <div className="max-w-4xl mx-auto px-6 py-10 space-y-6">
      {/* Estado general */}
      <div className="card p-6 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-2 text-xs font-medium px-3 py-1 rounded-full border ${TONE_CLASSES[status.tone]}`}
          >
            <span
              className={`w-2 h-2 rounded-full ${TONE_DOT[status.tone]} ${
                session.status === "running" ? "animate-soft-pulse" : ""
              }`}
            />
            {status.label}
          </span>
          {session.git_checkpoint?.is_git_repo && session.git_checkpoint.mission_branch && (
            <span
              className="inline-flex items-center gap-1 text-[11px] font-mono px-2.5 py-1 rounded-full bg-cream-100 border border-cream-200 text-ink-500"
              title="Los cambios se guardan en una rama separada para no afectar tu trabajo"
            >
              <GitBranch className="w-3 h-3" />
              {session.git_checkpoint.mission_branch}
            </span>
          )}
        </div>

        <h1 className="font-serif text-2xl text-ink-900 leading-snug">{session.user_prompt}</h1>
        <p className="text-sm text-ink-500">{status.hint}</p>

        <div className="space-y-1.5">
          <div className="flex justify-between text-[11px] text-ink-500">
            <span>Consumo del límite</span>
            <span className="font-mono">
              {(session.total_tokens_used || 0).toLocaleString()} / {session.max_budget_tokens.toLocaleString()}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-cream-200 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${usedPct > 85 ? "bg-clay-500" : "bg-sage-500"}`}
              style={{ width: `${usedPct}%` }}
            />
          </div>
        </div>

        {(session.status === "failed" ||
          session.status === "interrupted" ||
          isActive ||
          (session.git_checkpoint?.is_git_repo && touchedCount > 0)) && (
          <div className="flex flex-wrap gap-2 pt-1">
            {isActive && (
              <button
                type="button"
                disabled={isSafetyBusy}
                onClick={onStopMission}
                className="btn-ghost"
                title="Detiene a los agentes. Podrás continuar más tarde."
              >
                <Square className="w-3.5 h-3.5" />
                Detener tarea
              </button>
            )}
            {session.status === "failed" && (
              <button type="button" onClick={onRetryMission} className="btn-primary">
                <RotateCcw className="w-4 h-4" />
                Intentar de nuevo
              </button>
            )}
            {session.status === "interrupted" && (
              <button type="button" disabled={isSafetyBusy} onClick={onResume} className="btn-primary">
                <Play className="w-4 h-4" />
                Continuar donde quedó
              </button>
            )}
            {session.git_checkpoint?.is_git_repo && touchedCount > 0 && (
              <button
                type="button"
                disabled={isSafetyBusy}
                onClick={onRollback}
                className="btn-ghost"
                title="Devuelve los archivos a como estaban antes de esta tarea"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Deshacer cambios ({touchedCount} {touchedCount === 1 ? "archivo" : "archivos"})
              </button>
            )}
          </div>
        )}
      </div>

      {safetyBanner && (
        <div
          className={`px-5 py-3.5 rounded-2xl border text-sm ${
            safetyBanner.kind === "ok" ? TONE_CLASSES.sage : TONE_CLASSES.clay
          }`}
        >
          {safetyBanner.text}
        </div>
      )}

      {/* Permiso pendiente */}
      {gateItem && (() => {
        const info = explainApproval(gateItem);
        return (
          <div className="rounded-[1.25rem] border-2 border-clay-500/50 bg-clay-50 p-6 space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 shrink-0 rounded-full bg-white border border-clay-100 flex items-center justify-center text-clay-500">
                <ShieldAlert className="w-5 h-5" />
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-clay-700">Necesitamos tu permiso</div>
                <h2 className="text-base font-semibold text-ink-900 mt-0.5">{info.title}</h2>
                <p className="text-sm text-ink-500 mt-1">{info.detail}</p>
              </div>
            </div>

            {gateItem.diff_preview ? (
              <DiffViewer diffText={gateItem.diff_preview} />
            ) : (
              <pre className="rounded-2xl border border-cream-200 bg-white p-3 font-mono text-xs text-ink-700 overflow-x-auto max-h-48">
                {JSON.stringify(gateItem.arguments, null, 2)}
              </pre>
            )}

            <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
              <button
                type="button"
                disabled={isResolving}
                onClick={() => onDecision(gateItem.id, false)}
                className="btn-ghost"
              >
                <X className="w-4 h-4" />
                No, rechazar
              </button>
              <button
                type="button"
                disabled={isResolving}
                onClick={() => onDecision(gateItem.id, true)}
                className="btn-primary"
              >
                <Check className="w-4 h-4" />
                {isResolving ? "Aplicando…" : "Sí, permitir"}
              </button>
            </div>
          </div>
        );
      })()}

      {/* Progreso del equipo */}
      <div className="card p-6 space-y-5">
        <h2 className="text-sm font-semibold text-ink-900">Progreso del equipo</h2>
        {runs.length === 0 ? (
          <div className="flex items-center gap-3 text-sm text-ink-500 py-4">
            <span className="w-4 h-4 rounded-full border-2 border-sage-500 border-t-transparent animate-spin-slow" />
            Organizando el trabajo…
          </div>
        ) : (
          <ol className="relative space-y-5">
            {runs.map((run, idx) => {
              const a = agentLabel(run.agent_id);
              const s = statusInfo(run.status);
              const isLast = idx === runs.length - 1;
              return (
                <li key={run.id} className="relative flex gap-4">
                  {!isLast && <span className="absolute left-[19px] top-11 bottom-[-20px] w-px bg-cream-300" />}
                  <div className="w-10 h-10 shrink-0 rounded-full bg-cream-100 border border-cream-200 flex items-center justify-center text-lg">
                    {a.emoji}
                  </div>
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-ink-900">{a.name}</span>
                      <span className={`text-[11px] px-2 py-0.5 rounded-full border ${TONE_CLASSES[s.tone]}`}>
                        {s.label}
                      </span>
                    </div>
                    <p className="text-sm text-ink-500 line-clamp-3 whitespace-pre-wrap">
                      {run.result_summary || a.desc}
                    </p>
                    {run.error_message && (
                      <div className={`mt-2 rounded-xl border px-3 py-2 text-xs ${TONE_CLASSES.rose}`}>
                        {run.error_message}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {/* Resultado */}
      <div className="card p-6 space-y-3">
        <h2 className="text-sm font-semibold text-ink-900">Resultado final</h2>
        {session.final_output ? (
          <div className="text-sm text-ink-700 whitespace-pre-wrap leading-relaxed bg-white border border-cream-200 rounded-2xl p-5 max-h-96 overflow-y-auto">
            {session.final_output}
          </div>
        ) : (
          <p className="text-sm text-ink-500">El resumen aparecerá acá cuando los agentes terminen.</p>
        )}
      </div>

      {/* Detalles (plegables) */}
      <Section title="Notas que compartieron los agentes" count={blackboardEntries.length}>
        {blackboardEntries.length === 0 ? (
          <p className="text-sm text-ink-500">Todavía no guardaron notas.</p>
        ) : (
          <div className="space-y-3">
            {blackboardEntries.map(([k, v]) => (
              <div key={k} className="rounded-2xl bg-white border border-cream-200 p-4 space-y-1.5">
                <div className="text-xs font-semibold text-sage-700 capitalize">{k.replace(/_/g, " ")}</div>
                <div className="text-sm text-ink-700 whitespace-pre-wrap leading-relaxed">
                  {typeof v === "string" ? v : JSON.stringify(v, null, 2)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Actividad en vivo" count={visibleEvents.length}>
        {visibleEvents.length === 0 ? (
          <p className="text-sm text-ink-500">Los movimientos aparecerán acá en tiempo real.</p>
        ) : (
          <ul className="space-y-2 max-h-96 overflow-y-auto">
            {visibleEvents.map((ev, idx) => (
              <li key={ev.id || idx} className="flex items-start gap-3 text-sm">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-sage-500 shrink-0" />
                <span className="text-ink-700">{describeEvent(ev)}</span>
                {ev.timestamp && (
                  <span className="ml-auto text-[11px] font-mono text-ink-300 shrink-0">
                    {new Date(ev.timestamp).toLocaleTimeString()}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
