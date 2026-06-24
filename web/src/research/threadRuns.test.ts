import { describe, expect, it } from "vitest";

import { selectRunsForThread } from "./threadRuns";

const runs = [
  { run_id: "run-1", question: "First question", queued_at: "2026-06-22T12:00:00Z" },
  { run_id: "run-2", question: "Second question", queued_at: "2026-06-22T12:02:00Z" },
];

describe("selectRunsForThread", () => {
  it("returns an empty thread for the new research route", () => {
    expect(selectRunsForThread(runs, null)).toEqual([]);
  });

  it("returns the full selected research history in chronological order", () => {
    expect(selectRunsForThread([...runs].reverse(), "run-2")).toEqual(runs);
  });

  it("keeps the thread empty while an unknown selected run is loading", () => {
    expect(selectRunsForThread(runs, "run-pending")).toEqual([]);
  });
});
