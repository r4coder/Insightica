import { NavLink } from "react-router-dom";
import type { GeminiSessionStatus } from "../types";

const LINKS = [
  { to: "/", label: "Datasets" },
  { to: "/history", label: "Analysis history" },
  { to: "/settings", label: "Settings" },
];

export default function Nav({ status }: { status: GeminiSessionStatus | null }) {
  return (
    <header className="border-b border-line bg-panel">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <div className="flex items-baseline gap-3">
          <span className="font-display text-lg font-semibold tracking-tight">Multi-Agent Data Analyst</span>
          <span className="hidden font-mono text-xs text-graphite sm:inline">structured-data reasoning, not embeddings</span>
        </div>
        <nav className="flex items-center gap-6">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) =>
                `text-sm ${isActive ? "text-signal font-medium" : "text-graphite hover:text-ink"}`
              }
            >
              {l.label}
            </NavLink>
          ))}
          <span className="flex items-center gap-2 rounded border border-line px-2.5 py-1 text-xs">
            <span className={`h-2 w-2 rounded-full ${status?.connected ? "bg-signal" : "bg-alert"}`} />
            {status?.connected ? "Gemini connected" : "Gemini not connected"}
          </span>
        </nav>
      </div>
    </header>
  );
}
