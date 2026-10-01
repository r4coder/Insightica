import { ChangeEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, datasetApi } from "../services/api";
import type { Dataset } from "../types";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export default function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  async function refresh() {
    setLoading(true);
    try {
      setDatasets(await datasetApi.list());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  async function handleUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const dataset = await datasetApi.upload(file);
      await refresh();
      navigate(`/datasets/${dataset.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this dataset? This cannot be undone.")) return;
    await datasetApi.remove(id);
    refresh();
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold">Datasets</h1>
          <p className="text-sm text-graphite">Upload a CSV, XLSX or Parquet file to start asking questions about it.</p>
        </div>
        <label className="btn-primary cursor-pointer">
          {uploading ? "Uploading..." : "Upload dataset"}
          <input type="file" accept=".csv,.xlsx,.parquet" className="hidden" onChange={handleUpload} disabled={uploading} />
        </label>
      </div>

      {error && <p className="mt-4 rounded border border-alert/40 bg-alert/5 px-3 py-2 text-sm text-alert">{error}</p>}

      {loading ? (
        <p className="mt-8 text-sm text-graphite">Loading...</p>
      ) : datasets.length === 0 ? (
        <div className="panel mt-8 p-10 text-center">
          <p className="font-display text-lg">No datasets yet</p>
          <p className="mt-1 text-sm text-graphite">Upload sample_data/sales.csv to try a full analysis, or bring your own file.</p>
        </div>
      ) : (
        <div className="mt-6 overflow-hidden rounded border border-line">
          <table className="w-full text-left text-sm">
            <thead className="bg-line/30 font-mono text-xs uppercase tracking-wide text-graphite">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Rows</th>
                <th className="px-4 py-2 font-medium">Columns</th>
                <th className="px-4 py-2 font-medium">Size</th>
                <th className="px-4 py-2 font-medium">Uploaded</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.id} className="border-t border-line hover:bg-paper/60">
                  <td className="px-4 py-3">
                    <Link to={`/datasets/${d.id}`} className="font-medium text-signal-dark hover:underline">{d.name}</Link>
                  </td>
                  <td className="px-4 py-3 font-mono">{d.row_count.toLocaleString()}</td>
                  <td className="px-4 py-3 font-mono">{d.column_count}</td>
                  <td className="px-4 py-3 font-mono">{formatBytes(d.size_bytes)}</td>
                  <td className="px-4 py-3 text-graphite">{new Date(d.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => handleDelete(d.id)} className="text-xs text-alert hover:underline">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
