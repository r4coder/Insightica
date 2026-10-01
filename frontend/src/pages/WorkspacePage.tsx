import { FormEvent, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { analysisApi, datasetApi, ApiError } from "../services/api";
import type { Analysis, Dataset } from "../types";
import AgentTrace from "../components/AgentTrace";
import ChartPanel from "../components/ChartPanel";
import FindingCard from "../components/FindingCard";
import StatusBadge from "../components/StatusBadge";

const EXAMPLES = ["Why did revenue decrease in Q3?", "Which region had the highest revenue?", "Are there any unusual values in revenue?"];

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [thread, setThread] = useState<Analysis[]>([]);
  const [pending, setPending] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!id) return;
    datasetApi.get(id).then(setDataset);
  }, [id]);

  useEffect(() => () => { if (pollRef.current) window.clearTimeout(pollRef.current); }, []);

  function poll(analysisId: string) {
    const step = async () => {
      const updated = await analysisApi.get(analysisId);
      setPending(updated);
      if (updated.status === "running") {
        pollRef.current = window.setTimeout(step, 1200);
      } else {
        setThread((prev) => [...prev, updated]);
        setPending(null);
      }
    };
    step();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!id || !question.trim()) return;
    setError(null);
    try {
      const started = await analysisApi.start(id, question.trim(), sessionId);
      setSessionId(started.session_id);
      setQuestion("");
      poll(started.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the analysis.");
    }
  }

  const current = pending ?? thread[thread.length - 1] ?? null;

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <p className="label-text font-mono">AI Data Analyst</p>
      <h1 className="font-display text-2xl font-semibold">{dataset?.name ?? "Loading..."}</h1>

      <form onSubmit={handleSubmit} className="panel mt-6 p-4">
        <label className="label-text mb-1 block" htmlFor="question">Ask</label>
        <div className="flex gap-2">
          <input
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Why did revenue decline in Q3?"
            className="field-input"
          />
          <button type="submit" disabled={!question.trim() || !!pending} className="btn-primary whitespace-nowrap">
            {pending ? "Analyzing..." : "Analyze"}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" onClick={() => setQuestion(ex)} className="rounded border border-line px-2 py-1 text-xs text-graphite hover:border-signal hover:text-signal">
              {ex}
            </button>
          ))}
        </div>
        {error && <p className="mt-2 text-sm text-alert">{error}</p>}
      </form>

      {thread.slice(0, -1).reverse().map((a) => (
        <details key={a.id} className="panel mt-4 p-4">
          <summary className="cursor-pointer font-display text-sm font-semibold">
            {a.question} <StatusBadge status={a.status} />
          </summary>
          <div className="mt-3"><AnalysisView analysis={a} /></div>
        </details>
      ))}

      {current && (
        <div className="mt-6">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="font-display text-lg font-semibold">{current.question}</h2>
            <StatusBadge status={current.status} />
          </div>
          <div className="panel p-4">
            <h3 className="mb-2 label-text">Analysis progress</h3>
            <AgentTrace trace={current.trace} />
          </div>
          {current.status !== "running" && <div className="mt-4"><AnalysisView analysis={current} /></div>}
        </div>
      )}
    </div>
  );
}

function AnalysisView({ analysis }: { analysis: Analysis }) {
  const result = analysis.result;
  if (!result) return null;
  if (result.status === "failed" || !result.report) {
    return <p className="rounded border border-alert/40 bg-alert/5 px-3 py-2 text-sm text-alert">{result.error ?? "The analysis could not produce a verified report."}</p>;
  }
  const { report } = result;
  return (
    <div className="space-y-6">
      {result.warnings.length > 0 && (
        <ul className="rounded border border-gold/40 bg-gold/5 px-3 py-2 text-xs text-gold">
          {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      <div className="panel p-4">
        <h3 className="font-display text-base font-semibold">{report.title}</h3>
        <p className="mt-2 text-sm leading-relaxed">{report.executive_summary}</p>
      </div>
      <div className="panel p-4">
        <h3 className="label-text mb-2">Key findings</h3>
        <ul>{report.key_findings.map((f, i) => <FindingCard key={i} finding={f} />)}</ul>
      </div>
      {result.charts.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {result.charts.map((c) => <ChartPanel key={c.id} chart={c} />)}
        </div>
      )}
      {report.detailed_analysis && (
        <div className="panel p-4">
          <h3 className="label-text mb-2">Detailed analysis</h3>
          <p className="text-sm leading-relaxed">{report.detailed_analysis}</p>
        </div>
      )}
      {report.conclusion && (
        <div className="panel p-4">
          <h3 className="label-text mb-2">Conclusion</h3>
          <p className="text-sm leading-relaxed">{report.conclusion}</p>
        </div>
      )}
      <details className="panel p-4">
        <summary className="label-text cursor-pointer">Methodology & queries</summary>
        <p className="mt-2 whitespace-pre-line text-sm text-graphite">{report.methodology}</p>
        {result.queries.map((q) => (
          <div key={q.id} className="mt-3 rounded border border-line p-3">
            <p className="text-xs text-graphite">{q.purpose}</p>
            <pre className="mt-1 overflow-x-auto font-mono text-xs">{q.sql}</pre>
            <p className="mt-1 font-mono text-xs text-graphite">{q.error ? `Error: ${q.error}` : `${q.row_count} rows · ${q.elapsed_ms}ms`}</p>
          </div>
        ))}
      </details>
    </div>
  );
}
