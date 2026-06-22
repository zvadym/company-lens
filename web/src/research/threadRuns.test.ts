import { describe, expect, it } from "vitest";

import { selectRunsForThread } from "./threadRuns";

const runs = [
  { run_id: "run-1", question: "First question" },
  { run_id: "run-2", question: "Second question" },
];

describe("selectRunsForThread", () => {
  it("returns an empty thread for the new research route", () => {
    expect(selectRunsForThread(runs, null)).toEqual([]);
  });

  it("returns only the selected run instead of the full session history", () => {
    expect(selectRunsForThread(runs, "run-2")).toEqual([runs[1]]);
  });

  it("keeps the thread empty while an unknown selected run is loading", () => {
    expect(selectRunsForThread(runs, "run-pending")).toEqual([]);
  });
});
