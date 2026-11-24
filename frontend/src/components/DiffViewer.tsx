interface DiffViewerProps {
  diffText: string;
}

export function DiffViewer({ diffText }: DiffViewerProps) {
  return (
    <div className="rounded-2xl border border-cream-200 bg-white overflow-hidden">
      <div className="flex items-center gap-4 px-4 py-2 border-b border-cream-200 bg-cream-50 text-[11px] text-ink-500">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-sage-100 border border-sage-500/40" /> Se agrega
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-sm bg-[#fbeceb] border border-rose-soft/40" /> Se quita
        </span>
      </div>
      <pre className="p-3 font-mono text-[12px] overflow-x-auto max-h-72 leading-relaxed">
        {diffText.split("\n").map((line, idx) => {
          let cls = "text-ink-500 block px-2";
          if (line.startsWith("+++") || line.startsWith("---")) {
            cls = "text-ink-300 block px-2";
          } else if (line.startsWith("+")) {
            cls = "text-sage-700 bg-sage-50 block px-2 rounded";
          } else if (line.startsWith("-")) {
            cls = "text-rose-soft bg-[#fbeceb] block px-2 rounded";
          } else if (line.startsWith("@@")) {
            cls = "text-clay-500 block px-2 mt-2";
          }
          return (
            <span key={idx} className={cls}>
              {line || " "}
            </span>
          );
        })}
      </pre>
    </div>
  );
}
