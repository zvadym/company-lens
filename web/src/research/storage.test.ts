import { beforeEach, describe, expect, it } from "vitest";

import {
  loadResearchIndex,
  researchTitleFromQuestion,
  upsertResearchIndex,
} from "./storage";

describe("research storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("upserts and sorts anonymous research summaries by update time", () => {
    upsertResearchIndex({
      researchId: "research-1",
      title: "Older research",
      lastRunId: "run-1",
      lastQuestion: "Older question",
      status: "completed",
      createdAt: "2026-06-22T12:00:00Z",
      updatedAt: "2026-06-22T12:01:00Z",
    });
    upsertResearchIndex({
      researchId: "research-2",
      title: "Newer research",
      lastRunId: "run-2",
      lastQuestion: "Newer question",
      status: "running",
      createdAt: "2026-06-22T12:02:00Z",
      updatedAt: "2026-06-22T12:03:00Z",
    });

    expect(loadResearchIndex().map((item) => item.researchId)).toEqual([
      "research-2",
      "research-1",
    ]);
  });

  it("migrates the legacy browser session into the research index", () => {
    window.localStorage.setItem("company-lens.session.v1", "web-legacy");

    const index = loadResearchIndex();

    expect(index).toHaveLength(1);
    expect(index[0]).toMatchObject({
      researchId: "web-legacy",
      title: "Legacy research",
      lastRunId: null,
      lastQuestion: "",
      status: "completed",
    });
  });

  it("uses the first question as a compact research title", () => {
    expect(researchTitleFromQuestion("  Compare   Cloudflare revenue growth  ")).toBe(
      "Compare Cloudflare revenue growth",
    );
    expect(researchTitleFromQuestion("x".repeat(90))).toHaveLength(80);
  });
});
