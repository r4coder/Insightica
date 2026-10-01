import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { datasetApi } from "../services/api";
import type { Dataset, DatasetProfile } from "../types";

const ROLE_COLOR: Record<string, string> = {
  numeric: "text-signal-dark", categorical: "text-gold", date: "text-graphite", id: "text-graphite", text: "text-graphite",
};

export default function ExplorerPage() {
  const { id } = useParams<{ id: string }>();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [profile, setProfile] = useState<DatasetProfile | null>(null);

  useEffect(() => {
    if (!id) return;
    datasetApi.get(id).then(setDataset);
    datasetApi.profile(id).then(setProfile);
  }, [id]);

  if (!dataset || !profile) return <div className="mx-auto max-w-6xl px-6 py-10 text-sm text-graphite">Loading dataset...</div>;

  const sampleColumns = profile.sample_rows.length ? Object.keys(profile.sample_rows[0]) : [];

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex items-start justify-between">
        <div>
          <p className="label-text font-mono">Dataset explorer</p>
          <h1 className="font-display text-2xl font-semibold">{dataset.name}</h1>
        </div>
        <Link to={`/datasets/${dataset.id}/analyze`} className="btn-primary">Ask a question →</Link>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          ["Rows", profile.rows.toLocaleString()],
          ["Columns", String(profile.n_columns)],
          ["Duplicate rows", String(profile.duplicate_rows)],
          ["File type", dataset.file_type.toUpperCase()],
        ].map(([label, value]) => (
          <div key={label} className="panel p-4">
            <p className="label-text">{label}</p>
            <p className="font-display text-xl">{value}</p>
          </div>
        ))}
      </div>

      <h2 className="mt-8 font-display text-lg font-semibold">Columns</h2>
      <div className="mt-3 overflow-x-auto rounded border border-line">
        <table className="w-full text-left text-sm">
          <thead className="bg-line/30 font-mono text-xs uppercase tracking-wide text-graphite">
            <tr>
              <th className="px-4 py-2">Name</th><th className="px-4 py-2">Type</th><th className="px-4 py-2">Role</th>
              <th className="px-4 py-2">Missing</th><th className="px-4 py-2">Unique</th><th className="px-4 py-2">Details</th>
            </tr>
          </thead>
          <tbody>
            {profile.columns.map((c) => (
              <tr key={c.name} className="border-t border-line">
                <td className="px-4 py-2 font-mono">{c.name}</td>
                <td className="px-4 py-2 font-mono text-graphite">{c.dtype}</td>
                <td className={`px-4 py-2 font-mono ${ROLE_COLOR[c.role] ?? ""}`}>{c.role}</td>
                <td className="px-4 py-2 font-mono">{c.missing_pct}%</td>
                <td className="px-4 py-2 font-mono">{c.unique.toLocaleString()}</td>
                <td className="px-4 py-2 text-graphite">
                  {c.role === "numeric" && c.mean !== undefined ? `range ${c.min}–${c.max}, mean ${c.mean.toFixed(2)}` : ""}
                  {c.role === "date" && `${String(c.min).slice(0, 10)} → ${String(c.max).slice(0, 10)}`}
                  {c.top_values && c.top_values.slice(0, 4).map((t) => t.value).join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mt-8 font-display text-lg font-semibold">Sample rows</h2>
      <div className="mt-3 overflow-x-auto rounded border border-line">
        <table className="w-full text-left text-xs">
          <thead className="bg-line/30 font-mono uppercase tracking-wide text-graphite">
            <tr>{sampleColumns.map((c) => <th key={c} className="whitespace-nowrap px-3 py-2">{c}</th>)}</tr>
          </thead>
          <tbody>
            {profile.sample_rows.map((row, i) => (
              <tr key={i} className="border-t border-line font-mono">
                {sampleColumns.map((c) => <td key={c} className="whitespace-nowrap px-3 py-2">{String(row[c] ?? "")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
