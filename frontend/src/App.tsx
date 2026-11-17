import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  Clock,
  Cpu,
  FolderOpen,
  GitBranch,
  Layers,
  LayoutDashboard,
  Play,
  ShieldAlert,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import {
  WS_BASE,
  fetchHealth,
  fetchSessionState,
  fetchSessions,
  launchAsyncSession,
  launchPipeline,
  resolveApproval,
  type HealthResponse,
  type SessionStateResponse,
  type SystemEventDTO,
  type TaskSessionDTO,
  type ToolExecutionDTO,
} from "./api";

type ViewTab = "dashboard" | "mission";

export function App() {
  const [activeTab, setActiveTab] = useState<ViewTab>("mission");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessions, setSessions] = useState<TaskSessionDTO[]>([]);
  const [globalPending, setGlobalPending] = useState<ToolExecutionDTO[]>([]);

  const [mode, setMode] = useState<"single" | "pipeline">("pipeline");
  const [agentId, setAgentId] = useState("programador");
  const [workspacePath, setWorkspacePath] = useState("data/live_workspace");
  const [maxBudget, setMaxBudget] = useState(15000);
  const [prompt, setPrompt] = useState(
    "Analiza el workspace y crea 'math_utils.py' con funciones sumar(a, b) y multiplicar(a, b)."
  );

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionState, setSessionState] = useState<SessionStateResponse | null>(null);
  const [events, setEvents] = useState<SystemEventDTO[]>([]);
  const [isLaunching, setIsLaunching] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  async function refreshOverview() {
    try {
      const [h, s] = await Promise.all([fetchHealth(), fetchSessions()]);
      setHealth(h);
      setSessions(s.sessions);
      setGlobalPending(s.pending_approvals);
      if (!activeSessionId && s.sessions.length > 0) {
        setActiveSessionId(s.sessions[0].id);
      }
    } catch {
      setHealth(null);
    }
  }

  useEffect(() => {
    refreshOverview();
  }, []);

  useEffect(() => {
    if (!activeSessionId) return;
    fetchSessionState(activeSessionId).then(setSessionState).catch(() => {});

    wsRef.current?.close();
    const ws = new WebSocket(`${WS_BASE}/ws/sessions/${activeSessionId}`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const parsed: SystemEventDTO = JSON.parse(ev.data);
        setEvents((prev) => [...prev, parsed]);
        if (
          [
            "APPROVAL_REQUIRED",
            "APPROVAL_RESOLVED",
            "STEP_COMPLETED",
            "RUN_COMPLETED",
            "RUN_FAILED",
            "TOKEN_RECORDED",
          ].includes(parsed.event_type)
        ) {
          fetchSessionState(activeSessionId).then(setSessionState).catch(() => {});
          refreshOverview();
        }
      } catch {
        // ignore
      }
    };

    return () => ws.close();
  }, [activeSessionId]);
  async function handleDispatch(e?: React.FormEvent, customPrompt?: string, customMode?: "single" | "pipeline") {
    e?.preventDefault();
    const finalPrompt = customPrompt ?? prompt;
    const finalMode = customMode ?? mode;

    setErrorMsg(null);
    setIsLaunching(true);
    setEvents([]);
    setSessionState(null);
    setActiveTab("mission");

    try {
      if (finalMode === "single") {
        const res = await launchAsyncSession({
          agent_id: agentId,
          user_prompt: finalPrompt,
          workspace_path: workspacePath,
          max_budget_tokens: maxBudget,
        });
        setActiveSessionId(res.session_id);
      } else {
        const result = await launchPipeline({
          user_prompt: finalPrompt,
          workspace_path: workspacePath,
          max_budget_tokens: maxBudget,
          stages: [
            {
              node_id: "node_01_explorer",
              agent_id: "explorador",
              instruction:
                "Inspecciona el workspace y publica un resumen técnico en el Blackboard bajo la clave 'diagnostico'.",
            },
            {
              node_id: "node_02_builder",
              agent_id: "programador",
              instruction:
                "Lee 'diagnostico' en el Blackboard y ejecuta los cambios solicitados en el objetivo global.",
            },
          ],
        });
        setActiveSessionId(result.session.id);
        setSessionState(result);
      }
      await refreshOverview();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error al ejecutar misión");
    } finally {
      setIsLaunching(false);
    }
  }

  async function handleDecision(executionId: string, approved: boolean) {
    setIsResolving(true);
    setErrorMsg(null);
    try {
      const updated = await resolveApproval(executionId, approved);
      setSessionState(updated);
      await refreshOverview();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error al resolver aprobación");
    } finally {
      setIsResolving(false);
    }
  }

  const completedCount = sessions.filter((s) => s.status === "completed").length;
  const successRate =
    sessions.length > 0 ? Math.round((completedCount / sessions.length) * 100) : 100;
  const totalTokensAll = sessions.reduce((acc, s) => acc + (s.total_tokens_used || 0), 0);

  const currentPending = sessionState?.pending_approvals ?? [];
  const gateItem = currentPending[0] ?? globalPending[0] ?? null;
  const runs = sessionState?.runs ?? [];
  const blackboardEntries = Object.entries(sessionState?.session.blackboard ?? {});
  const tokensUsed = sessionState?.session.total_tokens_used ?? 0;
  const budgetMax = sessionState?.session.max_budget_tokens ?? maxBudget;
  const budgetPct = Math.min(100, Math.round((tokensUsed / Math.max(1, budgetMax)) * 100));
  const statusBadge = (status?: string) => {
    switch (status) {
      case "completed":
        return "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
      case "awaiting_approval":
        return "text-amber-400 bg-amber-500/10 border-amber-500/25";
      case "running":
        return "text-cyan-400 bg-cyan-500/10 border-cyan-500/20";
      case "failed":
        return "text-rose-400 bg-rose-500/10 border-rose-500/20";
      default:
        return "text-zinc-400 bg-zinc-800/60 border-zinc-700/50";
    }
  };

  return (
    <div className="min-h-screen bg-[#050507] text-[#f4f4f6] flex">
      {/* Minimal Sidebar */}
      <aside className="w-60 shrink-0 border-r border-[#1f222a] bg-[#08090c] flex flex-col justify-between select-none">
        <div>
          <div className="h-14 px-4 border-b border-[#1f222a] flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                <Cpu className="w-4 h-4" />
              </div>
              <span className="font-semibold text-sm tracking-tight text-white">AGENT LAB</span>
            </div>
            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-[#13151a] border border-[#1f222a] text-cyan-400">
              v{health?.version ?? "0.5"}
            </span>
          </div>

          <div className="px-4 pt-5 pb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
            Orchestration
          </div>
          <nav className="px-2 space-y-1">
            <button
              type="button"
              onClick={() => setActiveTab("dashboard")}
              className={`w-full flex items-center justify-between px-3 py-2 rounded text-xs transition cursor-pointer ${
                activeTab === "dashboard"
                  ? "bg-[#13151a] text-white border border-[#262a34] font-medium"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-[#0e1015]"
              }`}
            >
              <span className="flex items-center gap-2.5">
                <LayoutDashboard className="w-4 h-4 text-indigo-400" />
                Dashboard
              </span>
              <span className="font-mono text-[10px] text-zinc-500">{sessions.length}</span>
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("mission")}
              className={`w-full flex items-center justify-between px-3 py-2 rounded text-xs transition cursor-pointer ${
                activeTab === "mission"
                  ? "bg-[#13151a] text-white border border-[#262a34] font-medium"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-[#0e1015]"
              }`}
            >
              <span className="flex items-center gap-2.5">
                <GitBranch className="w-4 h-4 text-cyan-400" />
                Mission Control
              </span>
              {gateItem && (
                <span className="font-mono text-[10px] px-1.5 py-0.2 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30">
                  HITL
                </span>
              )}
            </button>
          </nav>

          {/* Registered Agents Mini List */}
          <div className="px-4 pt-6 pb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
            Active Agents ({health?.agents.length ?? 0})
          </div>
          <div className="px-3 space-y-1.5">
            {(health?.agents ?? []).map((ag) => (
              <div
                key={ag.id}
                className="px-2.5 py-2 rounded bg-[#0c0d10] border border-[#1a1d24] flex items-center justify-between"
              >
                <div className="truncate">
                  <div className="font-mono text-xs text-zinc-200">{ag.id}</div>
                  <div className="text-[10px] text-zinc-500 truncate">{ag.role}</div>
                </div>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
              </div>
            ))}
          </div>
        </div>

        {/* Node Status Footer */}
        <div className="p-3 border-t border-[#1f222a] bg-[#060709] space-y-2 font-mono text-[11px]">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-zinc-300">
              <span
                className={`w-2 h-2 rounded-full ${
                  health ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
                }`}
              />
              {health ? "Node: Connected" : "Node: Offline"}
            </span>
            <span className="text-zinc-500">127.0.0.1</span>
          </div>
          <div className="flex items-center justify-between text-[10px] text-zinc-500">
            <span>Storage</span>
            <span className="text-zinc-300">SQLite WAL</span>
          </div>
          <div className="flex items-center justify-between text-[10px] text-zinc-500">
            <span>Tools</span>
            <span className="text-cyan-400">{health?.tools.length ?? 0} registered</span>
          </div>
        </div>
      </aside>

      {/* Main Content Shell */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar */}
        <header className="h-14 border-b border-[#1f222a] bg-[#08090c]/90 backdrop-blur px-6 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 font-mono text-xs text-zinc-400">
            <span className="text-zinc-600">agent-lab</span>
            <span>/</span>
            <span className="text-cyan-400">{activeTab}</span>
            {activeSessionId && (
              <>
                <span>/</span>
                <span className="text-zinc-200">{activeSessionId.slice(0, 8)}</span>
              </>
            )}
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden md:flex items-center gap-4 font-mono text-[11px] px-3 py-1 rounded bg-[#0c0d10] border border-[#1f222a]">
              <div>
                <span className="text-zinc-500 mr-1.5">TOKENS</span>
                <span className="text-indigo-400">
                  {tokensUsed} / {budgetMax}
                </span>
              </div>
              <div className="w-16 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                <div
                  className="h-full bg-indigo-500 transition-all"
                  style={{ width: `${budgetPct}%` }}
                />
              </div>
            </div>

            <button
              type="button"
              onClick={() => setActiveTab("mission")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white transition cursor-pointer"
            >
              <Play className="w-3.5 h-3.5" />
              New Mission
            </button>
          </div>
        </header>

        {errorMsg && (
          <div className="mx-6 mt-4 px-4 py-2.5 rounded bg-rose-500/10 border border-rose-500/30 text-xs text-rose-300 flex items-center justify-between">
            <span>{errorMsg}</span>
            <button type="button" onClick={() => setErrorMsg(null)} className="text-rose-400">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* ==================== VIEW 1: DASHBOARD ==================== */}
        {activeTab === "dashboard" ? (
          <main className="p-6 space-y-6 max-w-7xl w-full mx-auto">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-lg font-semibold text-white tracking-tight">
                  Operations Dashboard
                </h1>
                <p className="text-xs text-zinc-500">
                  Telemetría real del enjambre local, historial SQLite y compuertas HITL
                </p>
              </div>
            </div>

            {/* 4 Minimalist KPI Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
              <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4">
                <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                  Registered Agents
                </div>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-white">
                    {health?.agents.length ?? 0}
                  </span>
                  <span className="font-mono text-xs text-cyan-400">local ready</span>
                </div>
              </div>

              <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4">
                <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                  Total Sessions
                </div>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-cyan-400">{sessions.length}</span>
                  <span className="font-mono text-xs text-zinc-500">in SQLite</span>
                </div>
              </div>

              <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4">
                <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                  Completion Rate
                </div>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-emerald-400">{successRate}%</span>
                  <span className="font-mono text-xs text-zinc-500">
                    {completedCount} completed
                  </span>
                </div>
              </div>

              <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4">
                <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                  Cumulative Tokens
                </div>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-indigo-400">
                    {totalTokensAll.toLocaleString()}
                  </span>
                  <span className="font-mono text-xs text-zinc-500">ledger</span>
                </div>
              </div>
            </div>

            {/* Split Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Executions Queue Table */}
              <div className="lg:col-span-8 bg-[#0c0d10] border border-[#1f222a] rounded-lg overflow-hidden">
                <div className="px-4 py-3 border-b border-[#1f222a] flex items-center justify-between">
                  <span className="text-xs font-semibold text-zinc-200">
                    Recent Executions Queue
                  </span>
                  <span className="font-mono text-[11px] text-zinc-500">
                    {sessions.length} registros
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-[#08090c] font-mono text-[10px] uppercase text-zinc-500 border-b border-[#1f222a]">
                      <tr>
                        <th className="py-2.5 px-4">Session</th>
                        <th className="py-2.5 px-4">Objective</th>
                        <th className="py-2.5 px-4">Status</th>
                        <th className="py-2.5 px-4">Tokens</th>
                        <th className="py-2.5 px-4 text-right">Inspect</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#16181f]">
                      {sessions.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-zinc-500">
                            Aún no hay sesiones registradas. Lanza tu primera misión.
                          </td>
                        </tr>
                      ) : (
                        sessions.map((s) => (
                          <tr
                            key={s.id}
                            onClick={() => {
                              setActiveSessionId(s.id);
                              setActiveTab("mission");
                            }}
                            className="hover:bg-[#13151a] transition cursor-pointer"
                          >
                            <td className="py-2.5 px-4 font-mono text-cyan-400">
                              #{s.id.slice(0, 8)}
                            </td>
                            <td className="py-2.5 px-4 text-zinc-200 max-w-xs truncate">
                              {s.user_prompt}
                            </td>
                            <td className="py-2.5 px-4">
                              <span
                                className={`inline-flex items-center px-2 py-0.5 rounded border font-mono text-[10px] ${statusBadge(
                                  s.status
                                )}`}
                              >
                                {s.status}
                              </span>
                            </td>
                            <td className="py-2.5 px-4 font-mono text-zinc-400">
                              {s.total_tokens_used}
                            </td>
                            <td className="py-2.5 px-4 text-right text-zinc-500">
                              <ArrowRight className="w-3.5 h-3.5 inline" />
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Right Column: HITL Gate + Quick Launch */}
              <div className="lg:col-span-4 space-y-6">
                {gateItem ? (
                  <div className="bg-[#0c0d10] border border-amber-500/40 rounded-lg p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-amber-400 flex items-center gap-1.5">
                        <ShieldAlert className="w-4 h-4" />
                        Human Approval Gate
                      </span>
                      <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">
                        {gateItem.risk_level}
                      </span>
                    </div>
                    <div className="font-mono text-xs text-zinc-300">{gateItem.tool_name}</div>
                    <pre className="bg-[#050507] border border-[#1f222a] rounded p-2.5 font-mono text-[11px] text-cyan-300 overflow-x-auto max-h-36">
                      {JSON.stringify(gateItem.arguments, null, 2)}
                    </pre>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        disabled={isResolving}
                        onClick={() => handleDecision(gateItem.id, false)}
                        className="py-1.5 rounded bg-[#13151a] hover:bg-rose-950/50 border border-[#262a34] text-rose-400 font-mono text-xs cursor-pointer"
                      >
                        Reject
                      </button>
                      <button
                        type="button"
                        disabled={isResolving}
                        onClick={() => handleDecision(gateItem.id, true)}
                        className="py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-mono text-xs font-medium cursor-pointer"
                      >
                        Approve Run
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4 text-xs text-zinc-500 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    Sin aprobaciones humanas pendientes.
                  </div>
                )}

                <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4 space-y-2.5">
                  <div className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                    Quick Launch Swarms
                  </div>
                  {[
                    {
                      title: "Workspace Audit & Summary",
                      desc: "Pipeline • Explorador → Programador",
                      prompt:
                        "Analiza los archivos existentes en el workspace y genera un resumen en 'RESUMEN.md'.",
                    },
                    {
                      title: "Create Python Utility Module",
                      desc: "Pipeline • Con aprobación HITL",
                      prompt:
                        "Crea un módulo 'utils.py' con validación de emails y formateo de fechas ISO.",
                    },
                  ].map((tpl) => (
                    <button
                      key={tpl.title}
                      type="button"
                      onClick={() => {
                        setPrompt(tpl.prompt);
                        handleDispatch(undefined, tpl.prompt, "pipeline");
                      }}
                      className="w-full text-left p-2.5 rounded bg-[#111318] hover:bg-[#161920] border border-[#1f222a] transition cursor-pointer"
                    >
                      <div className="text-xs font-medium text-zinc-200">{tpl.title}</div>
                      <div className="font-mono text-[10px] text-zinc-500 mt-0.5">{tpl.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </main>
        ) : (
          /* ==================== VIEW 2: MISSION CONTROL ==================== */
          <main className="flex-1 flex flex-col min-h-0">
            {/* Dispatch Prompt Bar */}
            <form
              onSubmit={(e) => handleDispatch(e)}
              className="border-b border-[#1f222a] bg-[#08090c] px-6 py-3 flex flex-wrap items-center gap-3"
            >
              <div className="flex rounded bg-[#0c0d10] border border-[#1f222a] p-0.5 font-mono text-[11px]">
                <button
                  type="button"
                  onClick={() => setMode("pipeline")}
                  className={`px-2.5 py-1 rounded cursor-pointer ${
                    mode === "pipeline" ? "bg-indigo-600 text-white" : "text-zinc-400"
                  }`}
                >
                  Pipeline (2 Agents)
                </button>
                <button
                  type="button"
                  onClick={() => setMode("single")}
                  className={`px-2.5 py-1 rounded cursor-pointer ${
                    mode === "single" ? "bg-indigo-600 text-white" : "text-zinc-400"
                  }`}
                >
                  Single Agent
                </button>
              </div>

              {mode === "single" && (
                <select
                  value={agentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  className="rounded bg-[#0c0d10] border border-[#1f222a] px-2.5 py-1.5 font-mono text-xs text-zinc-200"
                >
                  <option value="programador">programador</option>
                  <option value="explorador">explorador</option>
                </select>
              )}

              <div className="flex items-center gap-1.5 bg-[#0c0d10] border border-[#1f222a] rounded px-2.5 py-1.5">
                <FolderOpen className="w-3.5 h-3.5 text-zinc-500" />
                <input
                  type="text"
                  value={workspacePath}
                  onChange={(e) => setWorkspacePath(e.target.value)}
                  className="bg-transparent font-mono text-xs text-zinc-300 w-36 focus:outline-none"
                />
              </div>

              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe la misión para los agentes..."
                className="flex-1 min-w-[240px] rounded bg-[#0c0d10] border border-[#1f222a] focus:border-indigo-500 px-3 py-1.5 text-xs text-white focus:outline-none"
                required
              />

              <button
                type="submit"
                disabled={isLaunching || !health}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-semibold text-white transition cursor-pointer"
              >
                <Play className="w-3.5 h-3.5" />
                {isLaunching ? "Running..." : "Dispatch"}
              </button>
            </form>

            {/* Studio Grid: Left DAG + Logs | Right Inspector */}
            <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 min-h-0">
              {/* Center Canvas + Bottom Trace */}
              <div className="lg:col-span-8 flex flex-col border-r border-[#1f222a]">
                {/* Dot-Grid DAG Topology Canvas */}
                <div className="flex-1 bg-dot-grid p-6 flex flex-col justify-between min-h-[280px]">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[11px] px-2.5 py-1 rounded bg-[#0c0d10] border border-[#1f222a] text-zinc-400">
                      DAG TOPOLOGY • {runs.length} NODES
                    </span>
                    {sessionState && (
                      <span
                        className={`font-mono text-[11px] px-2.5 py-1 rounded border ${statusBadge(
                          sessionState.session.status
                        )}`}
                      >
                        {sessionState.session.status.toUpperCase()}
                      </span>
                    )}
                  </div>

                  {/* Nodes Flow */}
                  <div className="my-auto py-6 flex flex-wrap items-center justify-center gap-4">
                    {runs.length === 0 ? (
                      <div className="text-center space-y-1 bg-[#0c0d10]/90 border border-[#1f222a] px-6 py-5 rounded-lg">
                        <Bot className="w-6 h-6 text-indigo-400 mx-auto mb-2" />
                        <div className="text-xs font-medium text-zinc-200">
                          Listo para orquestar
                        </div>
                        <div className="font-mono text-[11px] text-zinc-500">
                          Escribe una instrucción arriba y pulsa Dispatch
                        </div>
                      </div>
                    ) : (
                      runs.map((run, idx) => (
                        <div key={run.id} className="flex items-center gap-4">
                          <div
                            className={`w-64 rounded-lg bg-[#0c0d10] border p-3.5 space-y-2 transition ${
                              run.status === "awaiting_approval"
                                ? "border-amber-500/60"
                                : run.status === "running"
                                ? "border-cyan-500/60"
                                : "border-[#232730]"
                            }`}
                          >
                            <div className="flex items-center justify-between font-mono text-[10px]">
                              <span className="text-zinc-500">
                                {run.dag_node_id || `NODE 0${idx + 1}`}
                              </span>
                              <span className={`px-1.5 py-0.5 rounded border ${statusBadge(run.status)}`}>
                                {run.status}
                              </span>
                            </div>
                            <div className="text-sm font-semibold text-white">{run.agent_id}</div>
                            <div className="font-mono text-[11px] text-zinc-400 flex items-center justify-between pt-1 border-t border-[#181b22]">
                              <span>Step {run.current_step}</span>
                              <span className="text-cyan-400">#{run.id.slice(0, 6)}</span>
                            </div>
                          </div>

                          {idx < runs.length - 1 && (
                            <ArrowRight className="w-5 h-5 text-cyan-500/70 shrink-0" />
                          )}
                        </div>
                      ))
                    )}
                  </div>

                  <div className="font-mono text-[10px] text-zinc-600 flex justify-between">
                    <span>WORKSPACE: {workspacePath}</span>
                    <span>BUDGET: {budgetMax} TOKENS</span>
                  </div>
                </div>

                {/* Bottom Stream Trace Console */}
                <div className="h-56 border-t border-[#1f222a] bg-[#060709] flex flex-col">
                  <div className="px-4 py-2 border-b border-[#181a20] flex items-center justify-between font-mono text-[11px]">
                    <span className="text-zinc-300 flex items-center gap-2">
                      <Terminal className="w-3.5 h-3.5 text-cyan-400" />
                      STREAM TRACE (WEBSOCKET)
                    </span>
                    <span className="text-zinc-500">{events.length} events</span>
                  </div>
                  <div className="flex-1 overflow-y-auto p-3 space-y-1.5 font-mono text-[11px]">
                    {events.length === 0 ? (
                      <div className="text-zinc-600 py-4 text-center">
                        Esperando eventos en tiempo real...
                      </div>
                    ) : (
                      events.map((ev, idx) => (
                        <div key={ev.id || idx} className="flex items-start gap-2.5">
                          <Activity className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                          <span className="text-cyan-400 shrink-0">[{ev.event_type}]</span>
                          <span className="text-zinc-400 break-all">
                            {ev.payload ? JSON.stringify(ev.payload) : ""}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Right Inspector Drawer */}
              <div className="lg:col-span-4 bg-[#08090c] p-5 space-y-5 overflow-y-auto">
                {/* HITL Gate Card */}
                {currentPending.length > 0 && (
                  <div className="rounded-lg border border-amber-500/50 bg-[#0d0c09] p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs font-semibold text-amber-400 flex items-center gap-1.5">
                        <ShieldAlert className="w-4 h-4" />
                        HITL GATE TRIGGERED
                      </span>
                      <span className="font-mono text-[10px] text-amber-300 uppercase">
                        {currentPending[0].risk_level}
                      </span>
                    </div>

                    <div className="text-xs text-zinc-300">
                      Herramienta solicitada:{" "}
                      <code className="text-amber-300">{currentPending[0].tool_name}</code>
                    </div>

                    <pre className="bg-[#050507] border border-[#1f222a] rounded p-3 font-mono text-[11px] text-emerald-300 overflow-x-auto max-h-52">
                      {typeof currentPending[0].arguments?.content === "string"
                        ? `// ${currentPending[0].arguments.path}\n${currentPending[0].arguments.content}`
                        : JSON.stringify(currentPending[0].arguments, null, 2)}
                    </pre>

                    <div className="grid grid-cols-2 gap-2 pt-1">
                      <button
                        type="button"
                        disabled={isResolving}
                        onClick={() => handleDecision(currentPending[0].id, false)}
                        className="flex items-center justify-center gap-1.5 py-2 rounded bg-[#13151a] hover:bg-rose-950/50 border border-[#262a34] text-rose-400 font-mono text-xs cursor-pointer"
                      >
                        <X className="w-3.5 h-3.5" />
                        Reject
                      </button>
                      <button
                        type="button"
                        disabled={isResolving}
                        onClick={() => handleDecision(currentPending[0].id, true)}
                        className="flex items-center justify-center gap-1.5 py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-mono text-xs font-semibold cursor-pointer"
                      >
                        <Check className="w-3.5 h-3.5" />
                        Approve & Execute
                      </button>
                    </div>
                  </div>
                )}

                {/* Blackboard Memory */}
                <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4 space-y-2.5">
                  <div className="font-mono text-[11px] uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-cyan-400" />
                    Shared Blackboard
                  </div>
                  {blackboardEntries.length === 0 ? (
                    <p className="text-xs text-zinc-600">Sin entradas en memoria compartida.</p>
                  ) : (
                    blackboardEntries.map(([k, v]) => (
                      <div
                        key={k}
                        className="rounded bg-[#050507] border border-[#1a1d24] p-2.5 space-y-1"
                      >
                        <div className="font-mono text-[11px] text-cyan-400">{k}</div>
                        <div className="text-xs text-zinc-300 whitespace-pre-wrap">
                          {typeof v === "string" ? v : JSON.stringify(v, null, 2)}
                        </div>
                      </div>
                    ))
                  )}
                </div>

                {/* Final Output */}
                <div className="bg-[#0c0d10] border border-[#1f222a] rounded-lg p-4 space-y-2.5">
                  <div className="font-mono text-[11px] uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-indigo-400" />
                    Mission Output
                  </div>
                  {sessionState?.session.final_output ? (
                    <div className="text-xs text-zinc-200 whitespace-pre-wrap bg-[#050507] border border-[#1a1d24] rounded p-3 max-h-64 overflow-y-auto">
                      {sessionState.session.final_output}
                    </div>
                  ) : (
                    <p className="text-xs text-zinc-600">
                      El resultado aparecerá aquí al completarse la ejecución.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </main>
        )}
      </div>
    </div>
  );
}

export default App;
