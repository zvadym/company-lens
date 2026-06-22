import { ExternalLink, FileSearch, ShieldAlert } from "lucide-react";

import type { ResearchCitation, ResearchSource } from "@/api/types";

export function SourcesPanel({ sources, citations }: {
  sources: ResearchSource[];
  citations: ResearchCitation[];
}) {
  const citationById = new Map(citations.map((citation) => [citation.evidence_id, citation]));
  return (
    <section className="inspector-section" aria-labelledby="sources-title">
      <div className="inspector-heading">
        <div>
          <span className="eyebrow">Evidence registry</span>
          <h2 id="sources-title">Sources</h2>
        </div>
        <span className="source-count">{sources.length}</span>
      </div>
      {sources.length === 0 ? (
        <div className="inspector-empty">
          <FileSearch size={22} />
          <p>Validated source previews will appear here when evidence is assembled.</p>
        </div>
      ) : (
        <ol className="source-list">
          {sources.map((source, index) => {
            const citation = citationById.get(source.evidence_id);
            const pages = source.page_start
              ? `p. ${source.page_start}${source.page_end && source.page_end !== source.page_start ? `–${source.page_end}` : ""}`
              : null;
            return (
              <li key={source.evidence_id}>
                <div className="source-index">{String(index + 1).padStart(2, "0")}</div>
                <div>
                  <div className="source-meta">
                    <span>{source.kind.replaceAll("_", " ")}</span>
                    {pages ? <span>{pages}</span> : null}
                    <span className={`source-status is-${source.status}`}>{source.status}</span>
                  </div>
                  <h3>{source.title}</h3>
                  {citation ? <p>{citation.summary}</p> : null}
                  {source.status === "invalid" || source.status === "inaccessible" ? (
                    <div className="source-warning"><ShieldAlert size={13} />Link may be unavailable</div>
                  ) : null}
                  <a href={source.exact_url} target="_blank" rel="noreferrer">
                    Inspect exact evidence <ExternalLink size={13} />
                  </a>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
