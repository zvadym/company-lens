import { describe, expect, it } from "vitest";

import type { ResearchCitation, ResearchSource } from "@/api/types";

import {
  groupEvidenceSources,
  presentEvidenceSource,
  sourceLinkLabel,
} from "./sourcePresentation";

const calculationSources: ResearchSource[] = [
  {
    evidence_id: "calculation:revenue-growth",
    title: "raw calculation",
    kind: "calculation",
    source_url: "https://example.test/2024",
    exact_url: "https://example.test/2024",
    status: "unchecked",
  },
  {
    evidence_id: "calculation:revenue-growth",
    title: "raw calculation",
    kind: "calculation",
    source_url: "https://example.test/2025",
    exact_url: "https://example.test/2025",
    status: "unchecked",
  },
];

const calculationCitation: ResearchCitation = {
  evidence_id: "calculation:revenue-growth",
  label: "Revenue growth",
  kind: "calculation",
  summary: "year_over_year_growth: [{'label': 'Cloudflare revenue 2024-12-31', 'value': '28.7551523237', 'observed_at': '2024-12-31'}, {'label': 'Cloudflare revenue 2025-12-31', 'value': '29.8456660353', 'observed_at': '2025-12-31'}]",
  source_urls: calculationSources.map((source) => source.source_url),
  lineage_refs: ["fact:2023", "fact:2024", "fact:2025"],
  claim_ids: ["claim:1"],
};

describe("source presentation", () => {
  it("groups multiple URLs for one evidence record", () => {
    const groups = groupEvidenceSources(calculationSources);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.sources).toHaveLength(2);
  });

  it("groups identical disclosures from distinct filings without losing provenance", () => {
    const filings: ResearchSource[] = [2024, 2025].map((year) => ({
      evidence_id: `section:cloud-${year}1231.htm:business`,
      title: "Item 1. Business Overview Cloudflare mission",
      kind: "document",
      source_url: `https://example.test/cloud-${year}1231.htm`,
      exact_url: `https://example.test/cloud-${year}1231.htm#business`,
      status: "unchecked",
    }));
    const filingCitations: ResearchCitation[] = filings.map((source) => ({
      evidence_id: source.evidence_id,
      label: "Item 1. Business",
      kind: "document",
      summary: "Cloudflare describes the same Connectivity Cloud demand trend.",
      source_urls: [source.source_url],
      lineage_refs: [source.evidence_id],
      claim_ids: ["claim:trend"],
    }));

    const groups = groupEvidenceSources(filings, filingCitations);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.evidenceIds).toHaveLength(2);
    expect(groups[0]?.sources).toHaveLength(2);
    expect(sourceLinkLabel(filings[0]!, 0, 2)).toBe("FY 2024 filing");
    expect(sourceLinkLabel(filings[1]!, 1, 2)).toBe("FY 2025 filing");
  });

  it("presents a calculation as rounded dated results instead of a raw payload", () => {
    const group = groupEvidenceSources(calculationSources)[0];
    expect(group).toBeDefined();

    const presentation = presentEvidenceSource(group!, calculationCitation);

    expect(presentation.title).toBe("Year-over-year growth");
    expect(presentation.statusLabel).toBe("derived");
    expect(presentation.summary).toBe("Derived from 3 evidence records.");
    expect(presentation.calculationPoints).toEqual([
      { label: "2024", value: "28.8%" },
      { label: "2025", value: "29.8%" },
    ]);
    expect(presentation.summary).not.toContain("'observed_at'");
  });

  it("formats annual currency facts with compact values and fiscal years", () => {
    const source: ResearchSource = {
      evidence_id: "financial_fact:revenue-2022",
      title: "Cloudflare revenue: 975241000.000000 USD at 2022-12-31",
      kind: "financial_fact",
      source_url: "https://example.test/filing",
      exact_url: "https://example.test/filing",
      status: "unchecked",
    };
    const group = groupEvidenceSources([source])[0];
    expect(group).toBeDefined();

    const presentation = presentEvidenceSource(group!, undefined);

    expect(presentation.title).toBe("Cloudflare revenue");
    expect(presentation.summary).toBe("$975.24M · FY 2022");
    expect(presentation.statusLabel).toBeNull();
  });

  it("keeps non-annual observation dates explicit", () => {
    const source: ResearchSource = {
      evidence_id: "financial_fact:revenue-q1-2024",
      title: "Cloudflare revenue: 378600000.000000 USD at 2024-03-31",
      kind: "financial_fact",
      source_url: "https://example.test/filing",
      exact_url: "https://example.test/filing",
      status: "unchecked",
    };
    const group = groupEvidenceSources([source])[0];
    expect(group).toBeDefined();

    expect(presentEvidenceSource(group!, undefined).summary).toBe("$378.6M · Mar 31, 2024");
  });
});
