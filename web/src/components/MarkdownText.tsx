import { useMessage } from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { useCallback, useMemo } from "react";
import remarkGfm from "remark-gfm";

import { useResearch } from "@/research/context";

import {
  buildEvidenceCitationTargets,
  evidenceIdFromCitationHref,
  formatEvidenceCitations,
  normalizeMarkdownTables,
} from "./evidenceCitations";

export default function MarkdownText() {
  const runId = useMessage((message) => {
    const custom = message.metadata.custom as { runId?: unknown };
    return typeof custom.runId === "string" ? custom.runId : null;
  });
  const { runs, focusEvidence } = useResearch();
  const run = runs.find((item) => item.run_id === runId);
  const targets = useMemo(
    () => buildEvidenceCitationTargets(
      run?.result?.sources ?? [],
      run?.result?.citations ?? [],
    ),
    [run?.result?.citations, run?.result?.sources],
  );
  const preprocess = useCallback(
    (markdown: string) => formatEvidenceCitations(normalizeMarkdownTables(markdown), targets),
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
                if (runId) focusEvidence(target.evidenceId, runId);
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
