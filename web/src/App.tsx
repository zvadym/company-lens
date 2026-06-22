import { Navigate, Route, Routes } from "react-router";

import { ResearchShell } from "@/components/ResearchShell";
import { ResearchProvider } from "@/research/context";

export default function App() {
  return (
    <Routes>
      <Route
        path="/research/:runId"
        element={(
          <ResearchProvider>
            <ResearchShell />
          </ResearchProvider>
        )}
      />
      <Route path="*" element={<Navigate to="/research/new" replace />} />
    </Routes>
  );
}
