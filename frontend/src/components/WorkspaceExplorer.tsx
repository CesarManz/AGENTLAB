import { FileCode2, FolderOpen, RefreshCw } from "lucide-react";
import type { WorkspaceFileDTO } from "../api";

interface WorkspaceExplorerProps {
  workspacePath: string;
  files: WorkspaceFileDTO[];
  selectedFile: { path: string; content: string } | null;
  onSelectFile: (path: string) => void;
  onRefresh: () => void;
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function WorkspaceExplorer({
  workspacePath,
  files,
  selectedFile,
  onSelectFile,
  onRefresh,
}: WorkspaceExplorerProps) {
  return (
    <div className="max-w-6xl mx-auto px-6 py-10 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="font-serif text-3xl text-ink-900">Tus archivos</h1>
          <p className="text-sm text-ink-500">
            Lo que crearon o modificaron los agentes en <code className="font-mono text-xs text-ink-700">{workspacePath}</code>.
            Tocá uno para verlo.
          </p>
        </div>
        <button type="button" onClick={onRefresh} className="btn-ghost">
          <RefreshCw className="w-3.5 h-3.5" />
          Actualizar
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[480px]">
        <div className="lg:col-span-4 card p-3 space-y-1 h-fit">
          {files.length === 0 ? (
            <div className="py-12 text-center space-y-2">
              <div className="text-3xl">📂</div>
              <p className="text-sm text-ink-500">Esta carpeta está vacía por ahora.</p>
            </div>
          ) : (
            files.map((f) => {
              const active = selectedFile?.path === f.path;
              return (
                <button
                  key={f.path}
                  type="button"
                  onClick={() => onSelectFile(f.path)}
                  className={`w-full flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl text-left text-sm transition cursor-pointer ${
                    active ? "bg-sage-50 text-sage-700" : "text-ink-700 hover:bg-cream-100"
                  }`}
                >
                  <span className="flex items-center gap-2.5 truncate">
                    <FileCode2 className={`w-4 h-4 shrink-0 ${active ? "text-sage-600" : "text-ink-300"}`} />
                    <span className="truncate font-mono text-xs">{f.path}</span>
                  </span>
                  <span className="text-[11px] text-ink-300 shrink-0">{formatSize(f.size_bytes)}</span>
                </button>
              );
            })
          )}
        </div>

        <div className="lg:col-span-8 card flex flex-col overflow-hidden">
          {selectedFile ? (
            <>
              <div className="px-5 py-3 border-b border-cream-200 flex items-center justify-between">
                <span className="font-mono text-xs text-ink-700">{selectedFile.path}</span>
                <span className="text-[11px] text-ink-500 px-2 py-0.5 rounded-full bg-cream-100 border border-cream-200">
                  Solo lectura
                </span>
              </div>
              <pre className="flex-1 p-5 font-mono text-xs text-ink-700 overflow-auto leading-relaxed bg-white">
                {selectedFile.content}
              </pre>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center space-y-3">
              <FolderOpen className="w-10 h-10 text-cream-300" />
              <p className="text-sm text-ink-500">Elegí un archivo de la lista para ver su contenido.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
