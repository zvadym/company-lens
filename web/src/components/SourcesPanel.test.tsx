import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SourcesPanel } from "./SourcesPanel";

afterEach(cleanup);

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
    expect(screen.getByRole("link", { name: /open source 1/i })).toHaveAttribute(
      "href",
      "https://example.test/filing#page=42",
    );
  });

  it("focuses and highlights evidence requested from an inline citation", () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: true }),
    });
    const source = {
      evidence_id: "document:risk",
      title: "Cloudflare 2025 10-K · Risk Factors",
      kind: "document" as const,
      source_url: "https://example.test/filing",
      exact_url: "https://example.test/filing#page=42",
      status: "available" as const,
      page_start: 42,
      page_end: 43,
    };

    const { container } = render(
      <SourcesPanel
        sources={[source]}
        citations={[]}
        evidenceFocus={{ evidenceId: source.evidence_id, requestId: 1 }}
      />,
    );

    const card = container.querySelector("li.is-focused");
    expect(card).toHaveClass("is-focused");
    expect(card).toHaveFocus();
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "center" });
  });
});
