import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { analysisApi } from "../services/api";
import type { Analysis } from "../types";
import StatusBadge from "../components/StatusBadge";

export default function HistoryPage() {
  const [items, setItems] = useState<Analysis[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    analysisApi.history().then(setItems).finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="font-display text-2xl font-semibold">Analysis history</h1>
      <p className="text-sm text-graphite">Previous questions across all datasets, most recent first.</p>

      {loading ? (
        <p className="mt-8 text-sm text-graphite">Loading...</p>
      ) : items.length === 0 ? (
        <div className="panel mt-8 p-10 text-center text-sm text-graphite">No analyses yet.</div>
      ) : (
        <ul className="mt-6 divide-y divide-line rounded border border-line">
          {items.map((a) => (
            <li key={a.id} className="p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <Link to={`/datasets/${a.dataset_id}/analyze`} className="font-medium text-signal-dark hover:underline">{a.question}</Link>
                  <p className="mt-0.5 text-xs text-graphite">{a.dataset_name} · {new Date(a.created_at).toLocaleString()}</p>
                </div>
                <StatusBadge status={a.status} />
              </div>
              {a.summary && <p className="mt-2 text-sm text-ink/80">{a.summary}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
