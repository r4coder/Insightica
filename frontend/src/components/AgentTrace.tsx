import type { TraceEvent } from "../types";
import StatusBadge from "./StatusBadge";

export default function AgentTrace({ trace }: { trace: TraceEvent[] }) {
  if (!trace.length) return null;
  return (
    <ol className="space-y-2">
      {trace.map((event, i) => (
        <li key={i} className="flex items-start gap-3 border-b border-line/60 py-2 last:border-0">
          <span className="w-40 shrink-0 font-mono text-xs text-graphite">{event.label}</span>
          <StatusBadge status={event.status} />
          <span className="flex-1 text-sm text-ink/90">{event.message}</span>
          <span className="shrink-0 font-mono text-xs text-graphite">{event.elapsed_ms.toFixed(0)}ms</span>
        </li>
      ))}
    </ol>
  );
}
