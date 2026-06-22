import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourcesPanel } from "./SourcesPanel";

describe("SourcesPanel", () => {
  it("renders hydrated evidence metadata and an exact deep link", () => {
    render(
      <SourcesPanel
        sources={[
          {
            evidence_id: "document:risk",
            title: "Cloudflare 2025 10-K · Risk Factors",
            kind: "document",
            source_url: "https://example.test/filing",
            exact_url: "https://example.test/filing#page=42",
            status: "available",
            page_start: 42,
            page_end: 43,
          },
        ]}
        citations={[
          {
            evidence_id: "document:risk",
            label: "Risk Factors",
            kind: "document",
            summary: "Management identifies competition as a material risk.",
            source_urls: ["https://example.test/filing"],
            lineage_refs: [],
            claim_ids: ["claim:1"],
          },
        ]}
      />,
    );

    expect(screen.getByText("Cloudflare 2025 10-K · Risk Factors")).toBeVisible();
    expect(screen.getByText("p. 42–43")).toBeVisible();
    expect(screen.getByRole("link", { name: /inspect exact evidence/i })).toHaveAttribute(
      "href",
      "https://example.test/filing#page=42",
    );
  });
});
