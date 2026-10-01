import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { configApi } from "../services/api";
import type { GeminiSessionStatus } from "../types";

export default function SettingsPage({ onStatusChange }: { onStatusChange: () => void }) {
  const [status, setStatus] = useState<GeminiSessionStatus | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => { configApi.status().then(setStatus); }, []);

  async function handleTest() {
    setTesting(true);
    try {
      const r = await configApi.test();
      setTestResult(r.message);
    } finally {
      setTesting(false);
    }
  }

  async function handleLogout() {
    await configApi.logout();
    onStatusChange();
    navigate("/setup");
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="font-display text-2xl font-semibold">Settings</h1>

      <div className="panel mt-6 p-5">
        <h2 className="label-text mb-2">Gemini configuration</h2>
        <div className="flex items-center gap-2 text-sm">
          <span className={`h-2 w-2 rounded-full ${status?.connected ? "bg-signal" : "bg-alert"}`} />
          {status?.connected ? `Connected (model: ${status.model})` : "Not connected"}
        </div>
        {status?.expires_at && (
          <p className="mt-1 text-xs text-graphite">
            Session expires at {new Date(status.expires_at * 1000).toLocaleTimeString()}
          </p>
        )}
        <div className="mt-4 flex gap-2">
          <button onClick={handleTest} disabled={testing || !status?.connected} className="btn-secondary">
            {testing ? "Testing..." : "Test connection"}
          </button>
          <button onClick={() => navigate("/setup")} className="btn-secondary">Replace API key</button>
          <button onClick={handleLogout} disabled={!status?.connected} className="btn-secondary text-alert hover:border-alert">
            Remove session
          </button>
        </div>
        {testResult && <p className="mt-3 text-sm text-graphite">{testResult}</p>}
      </div>
    </div>
  );
}
