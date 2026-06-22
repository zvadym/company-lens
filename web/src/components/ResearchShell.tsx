import {
  Activity,
  BookOpenText,
  ChevronRight,
  Clock3,
  FileText,
  Menu,
  Plus,
  SearchCode,
} from "lucide-react";

import { isTerminal } from "@/api/types";
import { useResearch } from "@/research/context";

import { ResearchThread } from "./ResearchThread";
import { groupEvidenceSources } from "./sourcePresentation";
import { SourcesPanel } from "./SourcesPanel";
import { TracePanel } from "./TracePanel";

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function HistorySidebar() {
  const { runs, selectedRunId, selectRun, newResearch } = useResearch();
  return (
    <aside className="history-sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">CL</div>
        <div><strong>CompanyLens</strong><span>Public market research</span></div>
      </div>
      <button className="new-research" type="button" onClick={newResearch}>
        <Plus size={15} /> New research
      </button>
      <div className="history-label"><Clock3 size={12} /> Recent runs</div>
      <nav aria-label="Research history" className="history-list">
        {runs.length === 0 ? <p className="history-empty">Your research history will appear here.</p> : null}
        {runs.toReversed().map((run) => (
          <button
            type="button"
            key={run.run_id}
            onClick={() => selectRun(run.run_id)}
            className={run.run_id === selectedRunId ? "is-selected" : ""}
          >
            <span className={`history-status is-${run.status}`} aria-label={run.status} />
            <span><strong>{run.question}</strong><small>{formatTime(run.queued_at)}</small></span>
            <ChevronRight size={13} />
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span>DEMO MODE</span>
        <p>Anonymous session · evidence links may open externally</p>
      </div>
    </aside>
  );
}

function MobileHistory() {
  const { runs, selectedRunId, selectRun } = useResearch();
  if (runs.length === 0) return null;
  return (
    <label className="mobile-history">
      <Menu size={14} />
      <span className="sr-only">Select research run</span>
      <select value={selectedRunId ?? ""} onChange={(event) => selectRun(event.target.value)}>
        <option value="" disabled>Research history</option>
        {runs.toReversed().map((run) => <option key={run.run_id} value={run.run_id}>{run.question}</option>)}
      </select>
    </label>
  );
}

function Inspector() {
  const {
    inspector,
    setInspector,
    events,
    sources,
    selectedRun,
    connection,
    evidenceFocus,
  } = useResearch();
  const citations = selectedRun?.result?.citations ?? [];
  const sourceCount = groupEvidenceSources(sources, citations).length;
  return (
    <aside className="inspector">
      <div className="inspector-tabs" role="tablist" aria-label="Run details">
        <button
          role="tab"
          aria-selected={inspector === "trace"}
          className={inspector === "trace" ? "is-active" : ""}
          onClick={() => setInspector("trace")}
          type="button"
        ><SearchCode size={14} /> Trace</button>
        <button
          role="tab"
          aria-selected={inspector === "sources"}
          className={inspector === "sources" ? "is-active" : ""}
          onClick={() => setInspector("sources")}
          type="button"
        ><FileText size={14} /> Sources <span>{sourceCount}</span></button>
      </div>
      {inspector === "trace" ? (
        <TracePanel events={events} connection={connection} />
      ) : (
        <SourcesPanel sources={sources} citations={citations} evidenceFocus={evidenceFocus} />
      )}
    </aside>
  );
}

export function ResearchShell() {
  const { selectedRun, runs, newResearch } = useResearch();
  const running = selectedRun ? !isTerminal(selectedRun.status) : false;
  return (
    <div className="app-shell">
      <HistorySidebar />
      <main className="research-main">
        <header className="research-header">
          <MobileHistory />
          <div className="header-context">
            <BookOpenText size={15} />
            <span>{selectedRun ? "Research session" : "New inquiry"}</span>
            {selectedRun ? <code>{selectedRun.run_id.slice(0, 8)}</code> : null}
          </div>
          <div className="header-status">
            {running ? <Activity size={14} /> : null}
            <span>{selectedRun?.status.replaceAll("_", " ") ?? `${runs.length} saved runs`}</span>
          </div>
          <button className="header-new" type="button" onClick={newResearch} aria-label="New research">
            <Plus size={15} />
          </button>
        </header>
        <ResearchThread />
      </main>
      <Inspector />
    </div>
  );
}
