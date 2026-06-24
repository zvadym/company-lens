import {
  Activity,
  BookOpenText,
  ChevronRight,
  Clock3,
  FileText,
  Menu,
  PanelRightClose,
  Plus,
  SearchCode,
} from "lucide-react";

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
  const { researches, researchId, selectResearch, newResearch } = useResearch();
  return (
    <aside className="history-sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">CL</div>
        <div><strong>CompanyLens</strong><span>Public market research</span></div>
      </div>
      <button className="new-research" type="button" onClick={newResearch}>
        <Plus size={15} /> New research
      </button>
      <div className="history-label"><Clock3 size={12} /> Recent research</div>
      <nav aria-label="Research history" className="history-list">
        {researches.length === 0 ? <p className="history-empty">Your research history will appear here.</p> : null}
        {researches.map((research) => (
          <button
            type="button"
            key={research.researchId}
            onClick={() => selectResearch(research.researchId)}
            className={research.researchId === researchId ? "is-selected" : ""}
          >
            <span className={`history-status is-${research.status}`} aria-label={research.status} />
            <span>
              <strong>{research.title}</strong>
              <small>{formatTime(research.updatedAt)}</small>
            </span>
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
  const { researches, researchId, selectResearch } = useResearch();
  if (researches.length === 0) return null;
  return (
    <label className="mobile-history">
      <Menu size={14} />
      <span className="sr-only">Select research</span>
      <select value={researchId ?? ""} onChange={(event) => selectResearch(event.target.value)}>
        <option value="" disabled>Research history</option>
        {researches.map((research) => (
          <option key={research.researchId} value={research.researchId}>{research.title}</option>
        ))}
      </select>
    </label>
  );
}

function Inspector() {
  const {
    inspector,
    setInspector,
    closeInspector,
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
        <button
          type="button"
          className="inspector-close"
          onClick={closeInspector}
          aria-label="Hide details panel"
        >
          <PanelRightClose size={15} />
        </button>
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
  const { researchId, selectedRun, activeRun, runs, inspectorOpen, newResearch } = useResearch();
  const running = activeRun !== null;
  const statusRun = activeRun ?? selectedRun;
  const shortResearchId = researchId?.slice(0, 12);
  return (
    <div className={`app-shell ${inspectorOpen ? "" : "is-inspector-closed"}`}>
      <HistorySidebar />
      <main className="research-main">
        <header className="research-header">
          <MobileHistory />
          <div className="header-context">
            <BookOpenText size={15} />
            <span>{selectedRun ? "Research session" : "New inquiry"}</span>
            {shortResearchId ? <code>{shortResearchId}</code> : null}
          </div>
          <div className="header-status">
            {running ? <Activity size={14} /> : null}
            <span>{statusRun?.status.replaceAll("_", " ") ?? `${runs.length} saved runs`}</span>
          </div>
          <button className="header-new" type="button" onClick={newResearch} aria-label="New research">
            <Plus size={15} />
          </button>
        </header>
        <ResearchThread />
      </main>
      {inspectorOpen ? <Inspector /> : null}
    </div>
  );
}
