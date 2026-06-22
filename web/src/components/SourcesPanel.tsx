import { ExternalLink, FileSearch, ShieldAlert } from "lucide-react";
import { useEffect } from "react";

import type { ResearchCitation, ResearchSource } from "@/api/types";
import type { EvidenceFocus } from "@/research/context";

import {
  groupEvidenceSources,
  presentEvidenceSource,
  sourceLinkLabel,
} from "./sourcePresentation";

export function SourcesPanel({ sources, citations, evidenceFocus = null }: {
  sources: ResearchSource[];
  citations: ResearchCitation[];
  evidenceFocus?: EvidenceFocus | null;
}) {
  const citationById = new Map(citations.map((citation) => [citation.evidence_id, citation]));
  const sourceGroups = groupEvidenceSources(sources, citations);
  const focusedGroup = evidenceFocus
    ? sourceGroups.find((group) => group.evidenceIds.includes(evidenceFocus.evidenceId))
    : undefined;

  useEffect(() => {
    if (!focusedGroup || !evidenceFocus) return;
    const element = document.getElementById(`source-${encodeURIComponent(focusedGroup.evidenceId)}`);
    if (!element) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    element.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "center" });
    element.focus({ preventScroll: true });
  }, [evidenceFocus, focusedGroup]);

  return (
    <section className="inspector-section" aria-labelledby="sources-title">
      <div className="inspector-heading">
        <div>
          <span className="eyebrow">Evidence registry</span>
          <h2 id="sources-title">Sources</h2>
        </div>
        <span className="source-count">{sourceGroups.length}</span>
      </div>
      {sourceGroups.length === 0 ? (
        <div className="inspector-empty">
          <FileSearch size={22} />
          <p>Validated source previews will appear here when evidence is assembled.</p>
        </div>
      ) : (
        <ol className="source-list">
          {sourceGroups.map((group, index) => {
            const source = group.sources[0];
            if (!source) return null;
            const citation = group.evidenceIds
              .map((evidenceId) => citationById.get(evidenceId))
              .find((item) => item !== undefined);
            const presentation = presentEvidenceSource(group, citation);
            const focused = focusedGroup?.evidenceId === group.evidenceId;
            const pages = source.page_start
              ? `p. ${source.page_start}${source.page_end && source.page_end !== source.page_start ? `–${source.page_end}` : ""}`
              : null;
            return (
              <li
                key={`${group.evidenceId}:${focused ? evidenceFocus?.requestId : 0}`}
                id={`source-${encodeURIComponent(group.evidenceId)}`}
                className={focused ? "is-focused" : undefined}
                tabIndex={-1}
              >
                <div className="source-index">{String(index + 1).padStart(2, "0")}</div>
                <div>
                  <div className="source-meta">
                    <span>{group.kind.replaceAll("_", " ")}</span>
                    {pages ? <span>{pages}</span> : null}
                    {presentation.statusLabel ? (
                      <span className={`source-status is-${presentation.statusLabel.replaceAll(" ", "-")}`}>
                        {presentation.statusLabel}
                      </span>
                    ) : null}
                  </div>
                  <h3>{presentation.title}</h3>
                  {presentation.calculationPoints.length > 0 ? (
                    <dl className="calculation-points">
                      {presentation.calculationPoints.map((point) => (
                        <div key={`${point.label}:${point.value}`}>
                          <dt>{point.label}</dt>
                          <dd>{point.value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                  {presentation.summary ? <p>{presentation.summary}</p> : null}
                  {presentation.statusLabel === "link unavailable" ? (
                    <div className="source-warning"><ShieldAlert size={13} />Link may be unavailable</div>
                  ) : null}
                  <div className="source-links">
                    {group.sources.map((item, sourceIndex) => (
                      <a
                        key={item.exact_url}
                        href={item.exact_url}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`Open source ${index + 1}${group.sources.length > 1 ? `, filing ${sourceIndex + 1}` : ""}: ${presentation.title}`}
                      >
                        {sourceLinkLabel(item, sourceIndex, group.sources.length)}
                        <ExternalLink size={13} />
                      </a>
                    ))}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
