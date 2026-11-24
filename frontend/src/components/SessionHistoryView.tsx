import { useState } from "react";
import { ArrowRight, Trash2 } from "lucide-react";
import type { TaskSessionDTO } from "../api";
import { TONE_CLASSES, TONE_DOT, statusInfo } from "../labels";

interface SessionHistoryViewProps {
  sessions: TaskSessionDTO[];
  agentsCount: number;
  totalCostUsd: number;
  onInspectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onClearAll: () => void;
}

function timeAgo(iso?: string) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "hace un momento";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return new Date(iso).toLocaleDateString();
}

export function SessionHistoryView({
  sessions,
  agentsCount,
  totalCostUsd,
  onInspectSession,
  onDeleteSession,
  onClearAll,
}: SessionHistoryViewProps) {
  const [filter, setFilter] = useState<"all" | "completed" | "attention">("all");
  const [confirmClear, setConfirmClear] = useState(false);

  const completedCount = sessions.filter((s) => s.status === "completed").length;
  const attentionCount = sessions.filter(
    (s) => s.status === "awaiting_approval" || s.status === "interrupted"
  ).length;
  const successRate = sessions.length > 0 ? Math.round((completedCount / sessions.length) * 100) : 0;
  const totalTokens = sessions.reduce((acc, s) => acc + (s.total_tokens_used || 0), 0);

  const filtered = sessions.filter((s) => {
    if (filter === "completed") return s.status === "completed";
    if (filter === "attention") return s.status === "awaiting_approval" || s.status === "interrupted";
    return true;
  });

  const stats = [
    { label: "Tareas realizadas", value: String(sessions.length) },
    { label: "Terminadas con éxito", value: `${successRate}%` },
    { label: "Tokens usados", value: totalTokens.toLocaleString() },
    { label: "Costo estimado", value: `US$ ${totalCostUsd.toFixed(4)}` },
  ];

  return (
    <div className="max-w-5xl mx-auto px-6 py-10 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="font-serif text-3xl text-ink-900">Historial</h1>
          <p className="text-sm text-ink-500">
            Todas tus tareas anteriores. Tocá una para ver qué hicieron los {agentsCount} agentes.
          </p>
        </div>
        {sessions.length > 0 &&
          (confirmClear ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-ink-500">¿Borrar todo el historial?</span>
              <button type="button" onClick={() => setConfirmClear(false)} className="btn-ghost">
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => {
                  setConfirmClear(false);
                  onClearAll();
                }}
                className="btn-ghost !border-rose-soft/40 !text-rose-soft"
              >
                Sí, borrar
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirmClear(true)} className="btn-ghost">
              <Trash2 className="w-3.5 h-3.5" />
              Limpiar historial
            </button>
          ))}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="card p-5">
            <div className="text-xs text-ink-500">{s.label}</div>
            <div className="mt-1 font-serif text-2xl text-ink-900">{s.value}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {[
          { id: "all" as const, label: `Todas · ${sessions.length}` },
          { id: "completed" as const, label: `Terminadas · ${completedCount}` },
          { id: "attention" as const, label: `Esperan tu acción · ${attentionCount}` },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setFilter(tab.id)}
            className={`px-4 py-1.5 rounded-full text-xs font-medium border transition cursor-pointer ${
              filter === tab.id
                ? "bg-ink-900 border-ink-900 text-cream-50"
                : "bg-cream-50 border-cream-300 text-ink-700 hover:bg-cream-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="card divide-y divide-cream-200 overflow-hidden">
        {filtered.length === 0 ? (
          <div className="py-14 text-center space-y-2">
            <div className="text-3xl">🗂️</div>
            <p className="text-sm text-ink-500">No hay tareas para mostrar.</p>
          </div>
        ) : (
          filtered.map((s) => {
            const st = statusInfo(s.status);
            return (
              <div
                key={s.id}
                role="button"
                tabIndex={0}
                onClick={() => onInspectSession(s.id)}
                onKeyDown={(e) => e.key === "Enter" && onInspectSession(s.id)}
                className="group flex items-center gap-4 px-5 py-4 hover:bg-cream-100/70 transition cursor-pointer"
              >
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${TONE_DOT[st.tone]}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-ink-900 truncate">{s.user_prompt}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
                    <span className={`px-2 py-0.5 rounded-full border ${TONE_CLASSES[st.tone]}`}>{st.label}</span>
                    <span>{timeAgo(s.created_at)}</span>
                    <span>· {s.total_tokens_used.toLocaleString()} tokens</span>
                  </div>
                </div>
                <button
                  type="button"
                  title="Eliminar esta tarea"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(s.id);
                  }}
                  className="p-2 rounded-full text-ink-300 hover:text-rose-soft hover:bg-[#fbeceb] opacity-0 group-hover:opacity-100 transition cursor-pointer"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
                <ArrowRight className="w-4 h-4 text-ink-300 group-hover:text-sage-600 transition" />
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
