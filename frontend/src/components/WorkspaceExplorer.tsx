import { FileCode2, FolderOpen, RefreshCw } from "lucide-react";
import type { WorkspaceFileDTO } from "../api";

interface WorkspaceExplorerProps {
  workspacePath: string;
  files: WorkspaceFileDTO[];
  selectedFile: { path: string; content: string } | null;
  onSelectFile: (path: string) => void;
  onRefresh: () => void;
}

export function WorkspaceExplorer({
  workspacePath,
  files,
  selectedFile,
  onSelectFile,
  onRefresh,
}: WorkspaceExplorerProps) {
  return (
    <div className="p-6 max-w-7xl w-full mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-white">Archivos del Workspace</h1>
          <p className="text-xs text-zinc-400 font-mono mt-0.5">{workspacePath}</p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0c0d10] hover:bg-[#14161c] border border-[#1f222a] text-xs text-zinc-300 cursor-pointer"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Actualizar Lista
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[480px]">
        <div className="lg:col-span-4 bg-[#0c0d10] border border-[#1f222a] rounded-xl p-4 space-y-2">
          <div className="text-xs font-semibold text-zinc-400 px-2 pb-2 border-b border-[#181b22]">
            Archivos ({files.length})
          </div>
          {files.length === 0 ? (
            <div className="py-12 text-center text-xs text-zinc-500">
              Esta carpeta aún no tiene archivos.
            </div>
          ) : (
            <div className="space-y-1">
              {files.map((f) => {
                const active = selectedFile?.path === f.path;
                return (
                  <button
                    key={f.path}
                    type="button"
                    onClick={() => onSelectFile(f.path)}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-left font-mono text-xs transition cursor-pointer ${
                      active
                        ? "bg-indigo-500/15 border border-indigo-500/40 text-indigo-200"
                        : "hover:bg-[#13151b] text-zinc-300 border border-transparent"
                    }`}
                  >
                    <span className="flex items-center gap-2 truncate">
                      <FileCode2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      <span className="truncate">{f.path}</span>
                    </span>
                    <span className="text-[10px] text-zinc-500 shrink-0 ml-2">
                      {f.size_bytes} B
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="lg:col-span-8 bg-[#0c0d10] border border-[#1f222a] rounded-xl flex flex-col overflow-hidden">
          {selectedFile ? (
            <>
              <div className="px-4 py-3 border-b border-[#1f222a] bg-[#08090c] flex items-center justify-between">
                <span className="font-mono text-xs text-cyan-300">{selectedFile.path}</span>
                <span className="font-mono text-[10px] text-zinc-500">Solo lectura</span>
              </div>
              <pre className="flex-1 p-4 font-mono text-xs text-zinc-200 overflow-auto leading-relaxed">
                {selectedFile.content}
              </pre>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-zinc-500 space-y-2">
              <FolderOpen className="w-8 h-8 text-zinc-700" />
              <p className="text-xs">Selecciona un archivo de la izquierda para inspeccionar su contenido.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}