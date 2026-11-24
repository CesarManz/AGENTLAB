import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Leaf,
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
  stopSession,
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

  async function handleStop() {
    if (!sessionState) return;
    setIsSafetyBusy(true);
    setSafetyBanner(null);
    try {
      const updated = await stopSession(sessionState.session.id);
      setSessionState(updated);
      setSafetyBanner({
        kind: "warn",
        text: "Detuviste la tarea. Podés continuarla o deshacer los cambios cuando quieras.",
      });
      await refreshOverview();
    } catch (err) {
      setSafetyBanner({
        kind: "warn",
        text: err instanceof Error ? err.message : "No se pudo detener la misión",
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

  const navItems: { id: ViewTab; label: string; icon: typeof PlusCircle; badge?: string; alert?: boolean }[] = [
    { id: "launch", label: "Nueva tarea", icon: PlusCircle },
    {
      id: "live",
      label: "En curso",
      icon: Activity,
      badge: pendingAttentionCount > 0 ? String(pendingAttentionCount) : undefined,
      alert: pendingAttentionCount > 0,
    },
    { id: "files", label: "Archivos", icon: FolderOpen },
    { id: "history", label: "Historial", icon: History },
  ];

  return (
    <div className="min-h-screen bg-cream-100 text-ink-900 flex flex-col">
      {/* Barra superior */}
      <header className="sticky top-0 z-20 bg-cream-100/85 backdrop-blur border-b border-cream-200">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between gap-4">
          <button
            type="button"
            onClick={() => setActiveTab("launch")}
            className="flex items-center gap-2.5 cursor-pointer"
          >
            <span className="w-8 h-8 rounded-full bg-sage-600 text-cream-50 flex items-center justify-center">
              <Leaf className="w-4 h-4" />
            </span>
            <span className="font-serif text-lg text-ink-900 tracking-tight">Agent Lab</span>
          </button>

          <nav className="flex items-center gap-1 bg-cream-50 border border-cream-200 rounded-full p-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveTab(item.id)}
                  className={`relative flex items-center gap-2 px-3.5 py-1.5 rounded-full text-sm transition cursor-pointer ${
                    active ? "bg-ink-900 text-cream-50" : "text-ink-700 hover:bg-cream-200"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span className="hidden sm:inline">{item.label}</span>
                  {item.badge && (
                    <span
                      className={`min-w-5 h-5 px-1.5 rounded-full text-[10px] font-semibold flex items-center justify-center ${
                        item.alert ? "bg-clay-500 text-white animate-soft-pulse" : "bg-cream-200 text-ink-700"
                      }`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>

          <div
            className="hidden md:flex items-center gap-2 text-xs text-ink-500"
            title={health ? `${health.agents.length} agentes y ${health.tools.length} herramientas disponibles` : ""}
          >
            <span className={`w-2 h-2 rounded-full ${health ? "bg-sage-500" : "bg-rose-soft"}`} />
            {health ? `${health.agents.length} agentes listos` : "Sin conexión"}
          </div>
        </div>
      </header>

      {/* Contenido */}
      <div className="flex-1">
        {!health && (
          <div className="max-w-3xl mx-6 md:mx-auto mt-6 px-5 py-4 rounded-2xl bg-clay-50 border border-clay-100 text-sm text-clay-700">
            <strong>No podemos conectarnos con el servidor.</strong> Asegurate de haber iniciado el backend
            (ejecutá <code className="font-mono text-xs">.\dev.ps1</code>) y recargá la página.
          </div>
        )}

        {errorMsg && (
          <div className="max-w-3xl mx-auto mt-6 px-5 py-3.5 rounded-2xl bg-[#fbeceb] border border-[#f2d3d0] text-sm text-rose-soft flex items-center justify-between gap-4">
            <span>{errorMsg}</span>
            <button type="button" onClick={() => setErrorMsg(null)} className="cursor-pointer" title="Cerrar">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {activeTab === "launch" && (
          <MissionLauncher
            mode={mode}
            setMode={setMode}
            agents={health?.agents ?? []}
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
            onStopMission={handleStop}
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