export const API_BASE = "http://127.0.0.1:8000";
export const WS_BASE = "ws://127.0.0.1:8000";

export interface AgentInfoDTO {
  id: string;
  name: string;
  role: string;
  model_tier: string;
  allowed_tools: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
  agents: AgentInfoDTO[];
  tools: string[];
}

export interface TaskSessionDTO {
  id: string;
  user_prompt: string;
  status: string;
  workspace_path: string;
  blackboard: Record<string, unknown>;
  max_budget_tokens: number;
  total_tokens_used: number;
  final_output: string | null;
  created_at?: string;
}

export interface AgentRunDTO {
  id: string;
  session_id: string;
  parent_run_id: string | null;
  dag_node_id: string | null;
  agent_id: string;
  task_instruction: string;
  status: string;
  current_step: number;
  result_summary: string | null;
  error_message: string | null;
}

export interface ToolExecutionDTO {
  id: string;
  tool_call_id: string;
  run_id: string;
  session_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk_level: string;
  status: string;
  output: string | null;
}

export interface SessionStateResponse {
  session: TaskSessionDTO;
  runs: AgentRunDTO[];
  pending_approvals: ToolExecutionDTO[];
}

export interface SystemEventDTO {
  id?: string;
  event_type: string;
  session_id: string;
  run_id?: string | null;
  timestamp?: string;
  payload?: Record<string, unknown>;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error("Backend no disponible");
  return res.json();
}

export async function fetchSessions(): Promise<{
  sessions: TaskSessionDTO[];
  pending_approvals: ToolExecutionDTO[];
}> {
  const res = await fetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error("No se pudieron cargar las sesiones");
  return res.json();
}

export async function launchAsyncSession(params: {
  agent_id: string;
  user_prompt: string;
  workspace_path: string;
  max_budget_tokens: number;
}): Promise<{ session_id: string; ws_url: string; status: string }> {
  const res = await fetch(`${API_BASE}/sessions/async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Error al iniciar sesión");
  }
  return res.json();
}

export async function launchPipeline(params: {
  user_prompt: string;
  workspace_path: string;
  max_budget_tokens: number;
  stages: { node_id: string; agent_id: string; instruction: string }[];
}): Promise<SessionStateResponse> {
  const res = await fetch(`${API_BASE}/pipelines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Error al ejecutar pipeline");
  }
  return res.json();
}

export async function fetchSessionState(sessionId: string): Promise<SessionStateResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`);
  if (!res.ok) throw new Error("No se pudo obtener el estado de la sesión");
  return res.json();
}

export async function resolveApproval(
  executionId: string,
  approved: boolean
): Promise<SessionStateResponse> {
  const res = await fetch(`${API_BASE}/approvals/${executionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Error al resolver aprobación");
  }
  return res.json();
}
