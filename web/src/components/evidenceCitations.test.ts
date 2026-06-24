import { describe, expect, it } from "vitest";

import type { ResearchCitation, ResearchSource } from "@/api/types";

import {
  buildEvidenceCitationTargets,
  evidenceIdFromCitationHref,
  formatEvidenceCitations,
  normalizeMarkdownTables,
} from "./evidenceCitations";

const sources: ResearchSource[] = [
  {
    evidence_id: "financial_fact:revenue-2025",
    title: "Cloudflare 2025 10-K",
    kind: "financial_fact",
    source_url: "https://example.test/filing",
    exact_url: "https://example.test/filing#revenue",
    status: "available",
  },
];

const citations: ResearchCitation[] = [
  {
    evidence_id: "financial_fact:revenue-2025",
    label: "2025 revenue",
    kind: "financial_fact",
    summary: "Cloudflare annual revenue for 2025.",
    source_urls: ["https://example.test/filing"],
    lineage_refs: [],
    claim_ids: ["claim:1"],
  },
];

describe("evidence citations", () => {
  it("replaces raw evidence IDs with numbered Markdown links", () => {
    const targets = buildEvidenceCitationTargets(sources, citations);
    const formatted = formatEvidenceCitations(
      "Revenue was $2.168 billion. [financial_fact:revenue-2025]",
      targets,
    );

    expect(formatted).toBe(
      "Revenue was $2.168 billion. [1](#evidence-citation-financial_fact%3Arevenue-2025)",
    );
    expect(evidenceIdFromCitationHref("#evidence-citation-financial_fact%3Arevenue-2025")).toBe(
      "financial_fact:revenue-2025",
    );
    expect(targets.get("financial_fact:revenue-2025")?.url).toBe(
      "https://example.test/filing#revenue",
    );
  });

  it("leaves unknown evidence markers unchanged", () => {
    expect(formatEvidenceCitations("Claim. [document:unknown]", new Map())).toBe(
      "Claim. [document:unknown]",
    );
  });

  it("assigns one source number to identical disclosures from different filings", () => {
    const duplicateSources: ResearchSource[] = [2024, 2025].map((year) => ({
      evidence_id: `section:cloud-${year}1231.htm:business`,
      title: "Item 1. Business",
      kind: "document",
      source_url: `https://example.test/${year}`,
      exact_url: `https://example.test/${year}#business`,
      status: "unchecked",
    }));
    const duplicateCitations: ResearchCitation[] = duplicateSources.map((source) => ({
      evidence_id: source.evidence_id,
      label: "Business overview",
      kind: "document",
      summary: "Identical disclosure text.",
      source_urls: [source.source_url],
      lineage_refs: [source.evidence_id],
      claim_ids: ["claim:1"],
    }));

    const targets = buildEvidenceCitationTargets(duplicateSources, duplicateCitations);

    expect(targets.get(duplicateSources[0]!.evidence_id)?.number).toBe(1);
    expect(targets.get(duplicateSources[1]!.evidence_id)?.number).toBe(1);
    expect(targets.get(duplicateSources[0]!.evidence_id)?.url).not.toBe(
      targets.get(duplicateSources[1]!.evidence_id)?.url,
    );
  });

  it("normalizes GFM tables that directly follow list items", () => {
    const markdown = [
      "## Supporting facts",
      "- revenue facts cover 2024-06-30 through 2026-03-31.",
      "| Period | Company | Metric | Value |",
      "|---|---|---|---:|",
      "| 2026-03-31 | Cloudflare, Inc | revenue | 639.755 million USD [financial_fact:revenue-2025] |",
    ].join("\n");

    expect(normalizeMarkdownTables(markdown)).toContain(
      "- revenue facts cover 2024-06-30 through 2026-03-31.\n\n| Period | Company | Metric | Value |",
    );
  });

  it("keeps citation links inside normalized table cells", () => {
    const targets = buildEvidenceCitationTargets(sources, citations);
    const markdown = normalizeMarkdownTables(
      [
        "- supporting facts.",
        "| Period | Value |",
        "|---|---:|",
        "| 2025 | 100 USD [financial_fact:revenue-2025] |",
      ].join("\n"),
    );

    expect(formatEvidenceCitations(markdown, targets)).toContain(
      "| 2025 | 100 USD [1](#evidence-citation-financial_fact%3Arevenue-2025) |",
    );
  });
});
