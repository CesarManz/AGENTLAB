import { useState } from "react";
import { ArrowRight, GitBranch, Trash2 } from "lucide-react";
import type { TaskSessionDTO } from "../api";

interface SessionHistoryViewProps {
  sessions: TaskSessionDTO[];
  agentsCount: number;
  totalCostUsd: number;
  onInspectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onClearAll: () => void;
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

  const completedCount = sessions.filter((s) => s.status === "completed").length;
  const successRate =
    sessions.length > 0 ? Math.round((completedCount / sessions.length) * 100) : 100;
  const totalTokens = sessions.reduce((acc, s) => acc + (s.total_tokens_used || 0), 0);

  const filtered = sessions.filter((s) => {
    if (filter === "completed") return s.status === "completed";
    if (filter === "attention") {
      return s.status === "awaiting_approval" || s.status === "interrupted";
    }
    return true;
  });

  const badgeStyle = (status: string) => {
    if (status === "completed") return "text-emerald-300 bg-emerald-500/10 border-emerald-500/25";
    if (status === "awaiting_approval" || status === "interrupted") {
      return "text-amber-300 bg-amber-500/15 border-amber-500/35";
    }
    if (status === "running") return "text-cyan-300 bg-cyan-500/10 border-cyan-500/25";
    return "text-rose-300 bg-rose-500/10 border-rose-500/25";
  };

  return (
    <div className="p-6 max-w-7xl w-full mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-white">Historial y Métricas</h1>
          <p className="text-xs text-zinc-400">
            Registro persistente en SQLite de todas las ejecuciones, costos y ramas de seguridad.
          </p>
        </div>

        {sessions.length > 0 && (
          <button
            type="button"
            onClick={onClearAll}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-rose-500/12 hover:bg-rose-500/22 border border-rose-500/35 text-rose-300 text-xs font-medium transition cursor-pointer"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Limpiar Historial ({sessions.length})
          </button>
        )}
      </div>

      {/* 4 KPIs Limpios */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-4">
          <div className="text-xs text-zinc-500">Agentes Disponibles</div>
          <div className="mt-1.5 text-2xl font-bold text-white">{agentsCount}</div>
        </div>
        <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-4">
          <div className="text-xs text-zinc-500">Misiones Totales</div>
          <div className="mt-1.5 text-2xl font-bold text-cyan-400">{sessions.length}</div>
        </div>
        <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-4">
          <div className="text-xs text-zinc-500">Tasa de Éxito</div>
          <div className="mt-1.5 text-2xl font-bold text-emerald-400">{successRate}%</div>
        </div>
        <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl p-4">
          <div className="text-xs text-zinc-500">Consumo Acumulado</div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-indigo-400">
              {totalTokens.toLocaleString()}
            </span>
            <span className="font-mono text-xs text-emerald-400">
              ${totalCostUsd.toFixed(4)}
            </span>
          </div>
        </div>
      </div>

      {/* Tabla con Filtros y Borrado */}
      <div className="bg-[#0c0d10] border border-[#1f222a] rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-[#1f222a] flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {[
              { id: "all" as const, label: `Todas (${sessions.length})` },
              { id: "completed" as const, label: `Completadas (${completedCount})` },
              { id: "attention" as const, label: "Requieren Atención" },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setFilter(tab.id)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition cursor-pointer ${
                  filter === tab.id
                    ? "bg-indigo-600 text-white"
                    : "bg-[#13151b] text-zinc-400 hover:text-zinc-200"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#08090c] font-mono text-[10px] uppercase text-zinc-500 border-b border-[#1f222a]">
              <tr>
                <th className="py-3 px-5">ID</th>
                <th className="py-3 px-5">Objetivo</th>
                <th className="py-3 px-5">Rama Git</th>
                <th className="py-3 px-5">Estado</th>
                <th className="py-3 px-5">Tokens</th>
                <th className="py-3 px-5 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#16181f]">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-zinc-500">
                    No hay misiones registradas.
                  </td>
                </tr>
              ) : (
                filtered.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => onInspectSession(s.id)}
                    className="hover:bg-[#13151b] transition cursor-pointer"
                  >
                    <td className="py-3 px-5 font-mono text-cyan-400">#{s.id.slice(0, 8)}</td>
                    <td className="py-3 px-5 text-zinc-200 max-w-md truncate">{s.user_prompt}</td>
                    <td className="py-3 px-5 font-mono text-[11px] text-zinc-400">
                      {s.git_checkpoint?.mission_branch ? (
                        <span className="inline-flex items-center gap-1 text-indigo-300">
                          <GitBranch className="w-3 h-3" />
                          {s.git_checkpoint.mission_branch}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-3 px-5">
                      <span className={`font-mono text-[10px] px-2 py-0.5 rounded border ${badgeStyle(s.status)}`}>
                        {s.status}
                      </span>
                    </td>
                    <td className="py-3 px-5 font-mono text-zinc-400">
                      {s.total_tokens_used.toLocaleString()}
                    </td>
                    <td className="py-3 px-5 text-right">
                      <div className="inline-flex items-center gap-2">
                        <button
                          type="button"
                          title="Eliminar sesión"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteSession(s.id);
                          }}
                          className="p-1.5 rounded hover:bg-rose-500/15 text-zinc-500 hover:text-rose-400 transition cursor-pointer"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        <ArrowRight className="w-4 h-4 text-zinc-400" />
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}