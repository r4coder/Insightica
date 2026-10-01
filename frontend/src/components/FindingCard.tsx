import type { Finding } from "../types";

const KIND_LABEL: Record<string, string> = {
  observed: "Observed",
  calculated: "Calculated",
  interpretation: "Interpretation",
};

export default function FindingCard({ finding }: { finding: Finding }) {
  return (
    <li className="border-b border-line/60 py-3 last:border-0">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm leading-relaxed text-ink">{finding.statement}</p>
        <span className="shrink-0 rounded border border-line px-2 py-0.5 font-mono text-[11px] text-graphite">
          {KIND_LABEL[finding.kind]}
        </span>
      </div>
      {finding.evidence.length > 0 && (
        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-graphite">
          {finding.evidence.map((ev, i) => (
            <div key={i} title="ref -> computed value">
              <dt className="inline text-graphite">{ev.ref}</dt>
              <dd className="inline">
                {" = "}
                {typeof ev.actual_value === "number" ? ev.actual_value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(ev.actual_value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}
