import { useEffect, useState, useCallback, type ReactElement } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Nav from "./components/Nav";
import SetupPage from "./pages/SetupPage";
import DatasetsPage from "./pages/DatasetsPage";
import ExplorerPage from "./pages/ExplorerPage";
import WorkspacePage from "./pages/WorkspacePage";
import HistoryPage from "./pages/HistoryPage";
import SettingsPage from "./pages/SettingsPage";
import { configApi } from "./services/api";
import type { GeminiSessionStatus } from "./types";

function RequireGemini({ status, children }: { status: GeminiSessionStatus | null; children: ReactElement }) {
  const location = useLocation();
  if (status === null) return null; // still loading
  if (!status.connected) return <Navigate to="/setup" state={{ from: location }} replace />;
  return children;
}

export default function App() {
  const [status, setStatus] = useState<GeminiSessionStatus | null>(null);

  const refreshStatus = useCallback(() => {
    return configApi.status().then(setStatus).catch(() => setStatus({ connected: false }));
  }, []);

  useEffect(() => { refreshStatus(); }, [refreshStatus]);

  return (
    <div className="min-h-screen">
      <Nav status={status} />
      <Routes>
        <Route path="/setup" element={<SetupPage onConnected={refreshStatus} />} />
        <Route path="/" element={<RequireGemini status={status}><DatasetsPage /></RequireGemini>} />
        <Route path="/datasets/:id" element={<RequireGemini status={status}><ExplorerPage /></RequireGemini>} />
        <Route path="/datasets/:id/analyze" element={<RequireGemini status={status}><WorkspacePage /></RequireGemini>} />
        <Route path="/history" element={<RequireGemini status={status}><HistoryPage /></RequireGemini>} />
        <Route path="/settings" element={<SettingsPage onStatusChange={refreshStatus} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
