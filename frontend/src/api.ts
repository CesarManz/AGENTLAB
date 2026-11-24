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

export interface GitCheckpointDTO {
  is_git_repo: boolean;
  original_branch?: string | null;
  mission_branch?: string | null;
  base_commit?: string | null;
  agent_touched_paths: string[];
  created_by_agent: string[];
}

export interface RollbackResultDTO {
  status: "rolled_back" | "blocked" | "not_git_repo" | "nothing_to_revert";
  message: string;
  reverted_files: string[];
  blocked_files: string[];
  restored_branch?: string | null;
}

export interface TaskSessionDTO {
  id: string;
  user_prompt: string;
  status: string;
  workspace_path: string;
  blackboard: Record<string, unknown>;
  max_budget_tokens: number;
  use_knowledge_graph?: boolean;
  git_checkpoint?: GitCheckpointDTO;
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
  diff_preview?: string | null;
  target_file_sha256?: string | null;
}

export interface SessionStateResponse {
  session: TaskSessionDTO;
  runs: AgentRunDTO[];
  pending_approvals: ToolExecutionDTO[];
  session_cost_usd?: number;
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
  total_cost_usd?: number;
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
  use_knowledge_graph?: boolean;
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
  use_knowledge_graph?: boolean;
  stages: { node_id: string; agent_id: string; instruction: string }[];
}): Promise<{ session_id: string; ws_url: string; status: string }> {
  const res = await fetch(`${API_BASE}/pipelines/async`, {
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

export interface WorkspaceFileDTO {
  path: string;
  size_bytes: number;
}

export async function fetchWorkspaceFiles(
  workspacePath: string
): Promise<{ workspace_path: string; files: WorkspaceFileDTO[] }> {
  const params = new URLSearchParams({ workspace_path: workspacePath });
  const res = await fetch(`${API_BASE}/workspace/files?${params.toString()}`);
  if (!res.ok) throw new Error("No se pudieron listar los archivos del workspace");
  return res.json();
}

export async function fetchWorkspaceFile(
  workspacePath: string,
  path: string
): Promise<{ path: string; content: string }> {
  const params = new URLSearchParams({ workspace_path: workspacePath, path });
  const res = await fetch(`${API_BASE}/workspace/file?${params.toString()}`);
  if (!res.ok) throw new Error("No se pudo leer el archivo");
  return res.json();
}


export async function launchAutoPipeline(params: {
  user_prompt: string;
  workspace_path: string;
  max_budget_tokens: number;
  use_knowledge_graph?: boolean;
}): Promise<{
  session_id: string;
  ws_url: string;
  status: string;
  rationale: string;
  planned_stages: { node_id: string; agent_id: string; instruction: string }[];
}> {
  const res = await fetch(`${API_BASE}/pipelines/auto`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Error al planificar misión");
  }
  return res.json();
}
export async function rollbackSession(sessionId: string): Promise<RollbackResultDTO> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/rollback`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Error al ejecutar rollback de la misión");
  }
  return res.json();
}

export async function resumeSession(sessionId: string): Promise<SessionStateResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/resume`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Error al reanudar la sesión");
  }
  return res.json();
}
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("No se pudo eliminar la sesión");
}

export async function clearSessions(): Promise<{ deleted_count: number }> {
  const res = await fetch(`${API_BASE}/sessions`, { method: "DELETE" });
  if (!res.ok) throw new Error("No se pudo limpiar el historial");
  return res.json();
}
export async function stopSession(sessionId: string): Promise<SessionStateResponse> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/stop`, { method: "POST" });
  if (!res.ok) throw new Error("No se pudo detener la misión");
  return res.json();
}