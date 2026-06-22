import {
  BarChart3,
  Binary,
  BrainCircuit,
  Check,
  CircleAlert,
  Database,
  GitBranch,
  LoaderCircle,
  Search,
  ShieldCheck,
} from "lucide-react";

import type { ResearchEvent } from "@/research/events";

const iconByType = {
  "run.status": LoaderCircle,
  "analysis.summary": BrainCircuit,
  "entities.summary": Search,
  "plan.summary": GitBranch,
  "node.status": Binary,
  "tool.status": Database,
  "validation.summary": ShieldCheck,
  "chart.ready": BarChart3,
  "answer.token": Check,
  "run.terminal": Check,
} as const;

function titleFor(event: ResearchEvent): string {
  switch (event.type) {
    case "run.status": return `Run ${event.data.status}`;
    case "analysis.summary": return `Intent · ${event.data.route.replaceAll("_", " ")}`;
    case "entities.summary": return "Entities resolved";
    case "plan.summary": return `${event.data.branches.length} execution branches`;
    case "node.status": return event.data.node.replaceAll("_", " ");
    case "tool.status": return event.data.kind.replaceAll("_", " ");
    case "validation.summary": return event.data.valid ? "Claims validated" : "Validation needs repair";
    case "chart.ready": return "Chart specification ready";
    case "answer.token": return "Validated answer streamed";
    case "run.terminal": return `Run ${event.data.status}`;
  }
}

function summaryFor(event: ResearchEvent): string {
  switch (event.type) {
    case "analysis.summary":
      return event.data.reason_codes.join(" · ") || "Question classified";
    case "entities.summary": {
      const names = event.data.entities
        .map((entity) => entity.canonical_value ?? entity.mention)
        .filter(Boolean);
      return names.join(", ") || "No explicit company entities";
    }
    case "plan.summary":
      return event.data.branches.map((branch) => branch.kind.replaceAll("_", " ")).join(" → ");
    case "node.status": return event.data.summary;
    case "tool.status": {
      if (event.data.cache_hit) return "Reused an exact session result";
      if (event.data.error_code) return event.data.error_code.replaceAll("_", " ");
      return `${event.data.status} · ${event.data.attempts} attempt${event.data.attempts === 1 ? "" : "s"}`;
    }
    case "validation.summary":
      return `${event.data.supported_claim_count}/${event.data.claim_count} claims supported`;
    case "chart.ready":
      return `${event.data.series_count} series · ${event.data.point_count} points`;
    case "run.status":
    case "run.terminal": return "Durable run state updated";
    case "answer.token": return "Only citation-validated text is exposed";
  }
}

function eventDetails(event: ResearchEvent): unknown {
  if (event.type === "answer.token") return null;
  return event.data;
}

export function TracePanel({ events, connection }: {
  events: ResearchEvent[];
  connection: "idle" | "connecting" | "live" | "reconnecting" | "closed";
}) {
  const visibleEvents = events.filter((event, index) => {
    if (event.type !== "answer.token") return true;
    return index === events.findIndex((candidate) => candidate.type === "answer.token");
  });

  return (
    <section className="inspector-section" aria-labelledby="trace-title">
      <div className="inspector-heading">
        <div>
          <span className="eyebrow">Live methodology</span>
          <h2 id="trace-title">Execution trace</h2>
        </div>
        <span className={`connection-pill is-${connection}`}>
          <span aria-hidden="true" />{connection}
        </span>
      </div>
      <p className="privacy-note">
        Structured decisions and tool outcomes only. Private model reasoning is never exposed.
      </p>
      {visibleEvents.length === 0 ? (
        <div className="inspector-empty">
          <BrainCircuit size={22} />
          <p>Submit a question to inspect how the research graph routes and validates it.</p>
        </div>
      ) : (
        <ol className="trace-list">
          {visibleEvents.map((event) => {
            const Icon = iconByType[event.type];
            const failed =
              (event.type === "node.status" || event.type === "tool.status") &&
              event.data.status === "failed";
            const running =
              (event.type === "node.status" || event.type === "tool.status") &&
              event.data.status === "started";
            return (
              <li key={event.id} className={failed ? "is-failed" : running ? "is-running" : ""}>
                <div className="trace-icon">
                  {failed ? <CircleAlert size={15} /> : <Icon size={15} />}
                </div>
                <div className="trace-copy">
                  <div className="trace-title-row">
                    <strong>{titleFor(event)}</strong>
                    {event.type === "node.status" && event.data.duration_ms != null ? (
                      <time>{event.data.duration_ms} ms</time>
                    ) : null}
                  </div>
                  <p>{summaryFor(event)}</p>
                  {eventDetails(event) ? (
                    <details>
                      <summary>Technical detail</summary>
                      <pre>{JSON.stringify(eventDetails(event), null, 2)}</pre>
                    </details>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
