interface DiffViewerProps {
  diffText: string;
}

export function DiffViewer({ diffText }: DiffViewerProps) {
  return (
    <pre className="bg-[#050507] border border-[#1f222a] rounded-lg p-3 font-mono text-[11px] overflow-x-auto max-h-64 leading-relaxed">
      {diffText.split("\n").map((line, idx) => {
        let cls = "text-zinc-400 block";
        if (line.startsWith("+") && !line.startsWith("+++")) {
          cls = "text-emerald-300 bg-emerald-500/10 px-1.5 rounded-xs block";
        } else if (line.startsWith("-") && !line.startsWith("---")) {
          cls = "text-rose-300 bg-rose-500/10 px-1.5 rounded-xs block";
        } else if (line.startsWith("@@")) {
          cls = "text-cyan-400 font-semibold block mt-1";
        }
        return (
          <span key={idx} className={cls}>
            {line || " "}
          </span>
        );
      })}
    </pre>
  );
}