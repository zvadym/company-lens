import type { ResearchCitation, ResearchSource } from "@/api/types";

import { groupEvidenceSources } from "./sourcePresentation";

export type EvidenceCitationTarget = {
  evidenceId: string;
  number: number;
  title: string;
  url: string;
};

const citationHrefPrefix = "#evidence-citation-";

export function buildEvidenceCitationTargets(
  sources: ResearchSource[],
  citations: ResearchCitation[],
): Map<string, EvidenceCitationTarget> {
  const citationById = new Map(citations.map((citation) => [citation.evidence_id, citation]));
  const targets = new Map<string, EvidenceCitationTarget>();

  const groups = groupEvidenceSources(sources, citations);
  for (const [index, group] of groups.entries()) {
    const source = group.sources[0];
    if (!source) continue;
    const citation = citationById.get(group.evidenceId);
    for (const evidenceId of group.evidenceIds) {
      const evidenceSource = group.sources.find((item) => item.evidence_id === evidenceId) ?? source;
      const evidenceCitation = citationById.get(evidenceId) ?? citation;
      targets.set(evidenceId, {
        evidenceId,
        number: index + 1,
        title: evidenceCitation?.label || evidenceSource.title,
        url: evidenceSource.exact_url,
      });
    }
  }

  for (const citation of citations) {
    const fallbackUrl = citation.source_urls.at(0);
    if (targets.has(citation.evidence_id) || !fallbackUrl) continue;
    targets.set(citation.evidence_id, {
      evidenceId: citation.evidence_id,
      number: targets.size + 1,
      title: citation.label,
      url: fallbackUrl,
    });
  }

  return targets;
}

export function formatEvidenceCitations(
  markdown: string,
  targets: Map<string, EvidenceCitationTarget>,
): string {
  let formatted = markdown;
  const evidenceIds = [...targets.keys()].toSorted((left, right) => right.length - left.length);

  for (const evidenceId of evidenceIds) {
    const target = targets.get(evidenceId);
    if (!target) continue;
    const marker = `[${evidenceId}]`;
    const link = `[${target.number}](${citationHrefPrefix}${encodeURIComponent(evidenceId)})`;
    formatted = formatted.split(marker).join(link);
  }

  return formatted;
}

export function evidenceIdFromCitationHref(href: string | undefined): string | null {
  if (!href?.startsWith(citationHrefPrefix)) return null;
  return decodeURIComponent(href.slice(citationHrefPrefix.length));
}
