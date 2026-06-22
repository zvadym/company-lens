import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { useCallback, useMemo } from "react";
import remarkGfm from "remark-gfm";

import { useResearch } from "@/research/context";

import {
  buildEvidenceCitationTargets,
  evidenceIdFromCitationHref,
  formatEvidenceCitations,
} from "./evidenceCitations";

export default function MarkdownText() {
  const { selectedRun, sources, focusEvidence } = useResearch();
  const targets = useMemo(
    () => buildEvidenceCitationTargets(sources, selectedRun?.result?.citations ?? []),
    [selectedRun?.result?.citations, sources],
  );
  const preprocess = useCallback(
    (markdown: string) => formatEvidenceCitations(markdown, targets),
    [targets],
  );

  return (
    <MarkdownTextPrimitive
      className="answer-markdown"
      defer
      preprocess={preprocess}
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => {
          const evidenceId = evidenceIdFromCitationHref(href);
          const target = evidenceId ? targets.get(evidenceId) : undefined;
          if (!target) return <a href={href}>{children}</a>;
          return (
            <a
              className="citation-link"
              href="#sources-title"
              onClick={(event) => {
                event.preventDefault();
                focusEvidence(target.evidenceId);
              }}
              title={`Show source ${target.number}: ${target.title}`}
              aria-label={`Show source ${target.number}: ${target.title}`}
            >
              {children}
            </a>
          );
        },
      }}
    />
  );
}
