import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, configApi } from "../services/api";

const AI_STUDIO_URL = "https://aistudio.google.com/app/apikey";

export default function SetupPage({ onConnected }: { onConnected: () => Promise<void> }) {
  const [apiKey, setApiKey] = useState("");
  const [reveal, setReveal] = useState(false);
  const [testState, setTestState] = useState<"idle" | "testing" | "ok" | "error">("idle");
  const [message, setMessage] = useState("");
  const [showHelp, setShowHelp] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const navigate = useNavigate();

  async function handleTest() {
    if (!apiKey.trim()) return;
    setTestState("testing");
    try {
      const result = await configApi.test(apiKey.trim());
      setTestState(result.valid ? "ok" : "error");
      setMessage(result.message);
    } catch (err) {
      setTestState("error");
      setMessage(err instanceof Error ? err.message : "Could not reach the backend.");
    }
  }

  async function handleContinue(e: FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setConnecting(true);
    try {
      await configApi.createSession(apiKey.trim());
      await onConnected();
      navigate("/");
    } catch (err) {
      setTestState("error");
      setMessage(err instanceof ApiError ? err.message : "Could not create a session.");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-73px)] max-w-xl flex-col justify-center px-6 py-16">
      <p className="label-text mb-2 font-mono">Setup</p>
      <h1 className="font-display text-3xl font-semibold leading-tight text-ink">Multi-Agent Data Analyst</h1>
      <p className="mt-2 max-w-md text-graphite">
        Turn natural-language questions into data-driven insights, backed by real SQL, statistics and validated
        findings. Connect your Gemini API key to power the agents.
      </p>

      <form onSubmit={handleContinue} className="panel mt-8 p-6">
        <label className="label-text mb-1 block" htmlFor="gemini-key">Gemini API key</label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <input
              id="gemini-key"
              type={reveal ? "text" : "password"}
              value={apiKey}
              onChange={(e) => { setApiKey(e.target.value); setTestState("idle"); }}
              placeholder="AIza..."
              className="field-input pr-16 font-mono"
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => setReveal((v) => !v)}
              className="absolute inset-y-0 right-2 text-xs text-graphite hover:text-ink"
            >
              {reveal ? "Hide" : "Show"}
            </button>
          </div>
          <button type="button" onClick={handleTest} disabled={!apiKey.trim() || testState === "testing"} className="btn-secondary whitespace-nowrap">
            {testState === "testing" ? "Testing..." : "Test connection"}
          </button>
        </div>

        <div className="mt-3 flex items-center gap-2 text-sm">
          <span className={`h-2 w-2 rounded-full ${testState === "ok" ? "bg-signal" : testState === "error" ? "bg-alert" : "bg-line"}`} />
          <span className={testState === "error" ? "text-alert" : testState === "ok" ? "text-signal-dark" : "text-graphite"}>
            {testState === "idle" ? "Not connected" : message}
          </span>
        </div>

        <button type="submit" disabled={testState !== "ok" || connecting} className="btn-primary mt-6 w-full">
          {connecting ? "Connecting..." : "Continue →"}
        </button>

        <p className="mt-4 text-xs text-graphite">
          Your Gemini API key is used only for your temporary session (held server-side, never in the browser)
          and is not stored permanently.
        </p>
      </form>

      <div className="mt-4">
        <button type="button" onClick={() => setShowHelp((v) => !v)} className="text-sm text-signal hover:text-signal-dark">
          {showHelp ? "Hide" : "How do I get a Gemini API key?"}
        </button>
        {showHelp && (
          <ol className="panel mt-2 list-decimal space-y-1 p-4 pl-8 text-sm text-graphite">
            <li>Open the official Google AI Studio website.</li>
            <li>Sign in with a Google account.</li>
            <li>Navigate to the API key section.</li>
            <li>Create a Gemini API key.</li>
            <li>Copy the key.</li>
            <li>Paste it into the field above.</li>
            <li>Click "Test Connection".</li>
            <li>Continue once the connection succeeds.</li>
          </ol>
        )}
        <a href={AI_STUDIO_URL} target="_blank" rel="noreferrer" className="btn-secondary mt-3 inline-flex">
          Get Gemini API key
        </a>
      </div>
    </div>
  );
}
