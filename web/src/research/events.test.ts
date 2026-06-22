import { describe, expect, it } from "vitest";

import { parseResearchEvent } from "./events";

describe("parseResearchEvent", () => {
  it("accepts a typed version two execution event", () => {
    const event = parseResearchEvent(
      JSON.stringify({
        id: 12,
        schema_version: "2",
        run_id: "11111111-1111-4111-8111-111111111111",
        type: "node.status",
        occurred_at: "2026-06-22T12:00:00Z",
        data: {
          step_id: "step-1",
          node: "resolve_entities",
          branch_id: null,
          status: "completed",
          attempt: 1,
          summary: "Entity resolution completed.",
          duration_ms: 18,
        },
      }),
    );

    expect(event?.type).toBe("node.status");
    if (event?.type === "node.status") expect(event.data.duration_ms).toBe(18);
  });

  it("rejects legacy, malformed, and private arbitrary payloads", () => {
    expect(parseResearchEvent("not json")).toBeNull();
    expect(
      parseResearchEvent(
        JSON.stringify({
          id: 1,
          schema_version: "1",
          run_id: "11111111-1111-4111-8111-111111111111",
          type: "node.status",
          occurred_at: "2026-06-22T12:00:00Z",
          data: { prompt: "private" },
        }),
      ),
    ).toBeNull();
  });
});
