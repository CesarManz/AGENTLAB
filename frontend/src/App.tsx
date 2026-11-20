import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Cpu,
  FolderOpen,
  History,
  PlusCircle,
  X,
} from "lucide-react";
import {
  WS_BASE,
  clearSessions,
  deleteSession,
  fetchHealth,
  fetchSessionState,
  fetchSessions,
  fetchWorkspaceFile,
  fetchWorkspaceFiles,
  launchAsyncSession,
  launchAutoPipeline,
  launchPipeline,
  resolveApproval,
  resumeSession,
  rollbackSession,
  type HealthResponse,
  type SessionStateResponse,
  type SystemEventDTO,
  type TaskSessionDTO,
  type ToolExecutionDTO,
  type WorkspaceFileDTO,
} from "./api";
import { LiveMissionMonitor } from "./components/LiveMissionMonitor";
import { MissionLauncher } from "./components/MissionLauncher";
import { SessionHistoryView } from "./components/SessionHistoryView";
import { WorkspaceExplorer } from "./components/WorkspaceExplorer";

type ViewTab = "launch" | "live" | "files" | "history";

export function App() {
  const [activeTab, setActiveTab] = useState<ViewTab>("launch");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sessions, setSessions] = useState<TaskSessionDTO[]>([]);
  const [globalPending, setGlobalPending] = useState<ToolExecutionDTO[]>([]);
  const [totalCostUsd, setTotalCostUsd] = useState(0);

  const [mode, setMode] = useState<"auto" | "single" | "pipeline">("auto");
  const [agentId, setAgentId] = useState("programador");
  const [workspacePath, setWorkspacePath] = useState("data/live_workspace");
  const [maxBudget, setMaxBudget] = useState(40000);
  const [useKnowledgeGraph, setUseKnowledgeGraph] = useState(true);
  const [prompt, setPrompt] = useState(
    "Analiza el workspace y crea 'math_utils.py' con funciones sumar(a, b) y multiplicar(a, b)."
  );

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionState, setSessionState] = useState<SessionStateResponse | null>(null);
  const [events, setEvents] = useState<SystemEventDTO[]>([]);
  const [isLaunching, setIsLaunching] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [isSafetyBusy, setIsSafetyBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [safetyBanner, setSafetyBanner] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

  const [wsFiles, setWsFiles] = useState<WorkspaceFileDTO[]>([]);
  const [selectedFile, setSelectedFile] = useState<{ path: string; content: string } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  async function refreshOverview() {
    try {
      const [h, s] = await Promise.all([fetchHealth(), fetchSessions()]);
      setHealth(h);
      setSessions(s.sessions);
      setGlobalPending(s.pending_approvals);
      setTotalCostUsd(s.total_cost_usd ?? 0);
      const wf = await fetchWorkspaceFiles(workspacePath);
      setWsFiles(wf.files);
      if (!activeSessionId && s.sessions.length > 0) {
        setActiveSessionId(s.sessions[0].id);
      }
    } catch {
      setHealth(null);
    }
  }

  useEffect(() => {
    refreshOverview();
  }, [workspacePath]);

  useEffect(() => {
    if (!activeSessionId) return;
    setSafetyBanner(null);
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

  async function handleLaunch(
    customPrompt?: string,
    customMode?: "auto" | "single" | "pipeline"
  ) {
    const finalPrompt = customPrompt ?? prompt;
    const finalMode = customMode ?? mode;

    setErrorMsg(null);
    setSafetyBanner(null);
    setIsLaunching(true);
    setEvents([]);
    setSessionState(null);
    setActiveTab("live");

    try {
      if (finalMode === "auto") {
        const res = await launchAutoPipeline({
          user_prompt: finalPrompt,
          workspace_path: workspacePath,
          max_budget_tokens: maxBudget,
          use_knowledge_graph: useKnowledgeGraph,
        });
        setActiveSessionId(res.session_id);
      } else if (finalMode === "single") {
        const res = await launchAsyncSession({
          agent_id: agentId,
          user_prompt: finalPrompt,
          workspace_path: workspacePath,
          max_budget_tokens: maxBudget,
          use_knowledge_graph: useKnowledgeGraph,
        });
        setActiveSessionId(res.session_id);
      } else {
        const result = await launchPipeline({
          user_prompt: finalPrompt,
          workspace_path: workspacePath,
          max_budget_tokens: maxBudget,
          use_knowledge_graph: useKnowledgeGraph,
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
        setActiveSessionId(result.session_id);
      }
      await refreshOverview();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error al iniciar la misión");
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

  async function handleRollback() {
    if (!sessionState) return;
    setIsSafetyBusy(true);
    setSafetyBanner(null);
    try {
      const res = await rollbackSession(sessionState.session.id);
      setSafetyBanner({
        kind: res.status === "rolled_back" ? "ok" : "warn",
        text: res.message,
      });
      const updated = await fetchSessionState(sessionState.session.id);
      setSessionState(updated);
      await refreshOverview();
    } catch (err) {
      setSafetyBanner({
        kind: "warn",
        text: err instanceof Error ? err.message : "Error al revertir cambios",
      });
    } finally {
      setIsSafetyBusy(false);
    }
  }

  async function handleResume() {
    if (!sessionState) return;
    setIsSafetyBusy(true);
    setSafetyBanner(null);
    try {
      const updated = await resumeSession(sessionState.session.id);
      setSessionState(updated);
      setSafetyBanner({ kind: "ok", text: "Sesión reanudada correctamente." });
      await refreshOverview();
    } catch (err) {
      setSafetyBanner({
        kind: "warn",
        text: err instanceof Error ? err.message : "No se pudo reanudar la sesión",
      });
    } finally {
      setIsSafetyBusy(false);
    }
  }

  const pendingAttentionCount =
    (sessionState?.pending_approvals.length ?? 0) || globalPending.length;

  const navItems: { id: ViewTab; label: string; icon: typeof PlusCircle; badge?: string }[] = [
    { id: "launch", label: "Nueva Misión", icon: PlusCircle },
    {
      id: "live",
      label: "Misión en Vivo",
      icon: Activity,
      badge: pendingAttentionCount > 0 ? `${pendingAttentionCount} HITL` : undefined,
    },
    {
      id: "files",
      label: "Archivos Workspace",
      icon: FolderOpen,
      badge: wsFiles.length > 0 ? String(wsFiles.length) : undefined,
    },
    {
      id: "history",
      label: "Historial & Métricas",
      icon: History,
      badge: sessions.length > 0 ? String(sessions.length) : undefined,
    },
  ];

  return (
    <div className="min-h-screen bg-[#050507] text-[#f4f4f6] flex">
      {/* Sidebar Limpio */}
      <aside className="w-64 shrink-0 sticky top-0 h-screen overflow-y-auto border-r border-[#1f222a] bg-[#08090c] flex flex-col justify-between select-none">
        <div>
          <div className="h-14 px-5 border-b border-[#1f222a] flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                <Cpu className="w-4 h-4" />
              </div>
              <span className="font-semibold text-sm tracking-tight text-white">AGENT LAB</span>
            </div>
            <span className="font-mono text-[10px] px-2 py-0.5 rounded-full bg-[#13151a] border border-[#1f222a] text-cyan-400">
              v0.9
            </span>
          </div>

          <div className="px-5 pt-5 pb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
            Espacios de Trabajo
          </div>
          <nav className="px-3 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs transition cursor-pointer ${
                    active
                      ? "bg-[#141720] text-white border border-[#282d3b] font-medium"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-[#0e1015]"
                  }`}
                >
                  <span className="flex items-center gap-2.5">
                    <Icon className={`w-4 h-4 ${active ? "text-indigo-400" : "text-zinc-500"}`} />
                    {item.label}
                  </span>
                  {item.badge && (
                    <span
                      className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
                        item.badge.includes("HITL")
                          ? "bg-amber-500/20 text-amber-300 border border-amber-500/35"
                          : "bg-[#13151a] text-zinc-400"
                      }`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          {/* Agentes Registrados */}
          <div className="px-5 pt-6 pb-2 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
            Equipo Disponible ({health?.agents.length ?? 0})
          </div>
          <div className="px-3 space-y-1.5">
            {(health?.agents ?? []).map((ag) => (
              <div
                key={ag.id}
                className="px-3 py-2 rounded-lg bg-[#0c0d10] border border-[#1a1d24] flex items-center justify-between"
              >
                <div className="truncate">
                  <div className="text-xs font-medium text-zinc-200 capitalize">{ag.id}</div>
                  <div className="text-[10px] text-zinc-500 truncate">{ag.role}</div>
                </div>
                <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
              </div>
            ))}
          </div>
        </div>

        {/* Estado del Servidor */}
        <div className="p-4 border-t border-[#1f222a] bg-[#060709] space-y-1.5 font-mono text-[11px]">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-zinc-300">
              <span
                className={`w-2 h-2 rounded-full ${
                  health ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
                }`}
              />
              {health ? "Servidor Activo" : "Desconectado"}
            </span>
          </div>
          <div className="flex items-center justify-between text-[10px] text-zinc-500">
            <span>Herramientas</span>
            <span className="text-cyan-400">{health?.tools.length ?? 0} activas</span>
          </div>
        </div>
      </aside>

      {/* Área Principal */}
      <div className="flex-1 flex flex-col min-w-0">
        {errorMsg && (
          <div className="mx-6 mt-4 px-4 py-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-xs text-rose-300 flex items-center justify-between">
            <span>{errorMsg}</span>
            <button type="button" onClick={() => setErrorMsg(null)} className="text-rose-400 cursor-pointer">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {activeTab === "launch" && (
          <MissionLauncher
            mode={mode}
            setMode={setMode}
            agentId={agentId}
            setAgentId={setAgentId}
            workspacePath={workspacePath}
            setWorkspacePath={setWorkspacePath}
            maxBudget={maxBudget}
            setMaxBudget={setMaxBudget}
            useKnowledgeGraph={useKnowledgeGraph}
            setUseKnowledgeGraph={setUseKnowledgeGraph}
            prompt={prompt}
            setPrompt={setPrompt}
            isLaunching={isLaunching}
            isConnected={Boolean(health)}
            onLaunch={handleLaunch}
          />
        )}

        {activeTab === "live" && (
          <LiveMissionMonitor
            sessionState={sessionState}
            events={events}
            isResolving={isResolving}
            isSafetyBusy={isSafetyBusy}
            safetyBanner={safetyBanner}
            onDecision={handleDecision}
            onRollback={handleRollback}
            onResume={handleResume}
            onNewMission={() => setActiveTab("launch")}
            onRetryMission={() => handleLaunch(sessionState?.session.user_prompt)}
          />
        )}

        {activeTab === "files" && (
          <WorkspaceExplorer
            workspacePath={workspacePath}
            files={wsFiles}
            selectedFile={selectedFile}
            onSelectFile={async (path) => {
              const data = await fetchWorkspaceFile(workspacePath, path);
              setSelectedFile(data);
            }}
            onRefresh={refreshOverview}
          />
        )}

        {activeTab === "history" && (
          <SessionHistoryView
            sessions={sessions}
            agentsCount={health?.agents.length ?? 0}
            totalCostUsd={totalCostUsd}
            onInspectSession={(id) => {
              setActiveSessionId(id);
              setActiveTab("live");
            }}
            onDeleteSession={async (id) => {
              await deleteSession(id);
              if (activeSessionId === id) {
                setActiveSessionId(null);
                setSessionState(null);
              }
              await refreshOverview();
            }}
            onClearAll={async () => {
              await clearSessions();
              setActiveSessionId(null);
              setSessionState(null);
              setEvents([]);
              await refreshOverview();
            }}
          />
        )}
      </div>
    </div>
  );
}

export default App;