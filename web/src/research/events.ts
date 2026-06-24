import { z } from "zod";

const statusSchema = z.enum([
  "queued",
  "running",
  "cancellation_requested",
  "completed",
  "partial",
  "abstained",
  "failed",
  "cancelled",
  "timed_out",
]);

const eventBase = {
  id: z.number().int().nonnegative(),
  schema_version: z.literal("2"),
  run_id: z.string().uuid(),
  occurred_at: z.string(),
};

const runStatusEvent = z.object({
  ...eventBase,
  type: z.literal("run.status"),
  data: z.object({ status: statusSchema }),
});

const analysisEvent = z.object({
  ...eventBase,
  type: z.literal("analysis.summary"),
  data: z.object({
    route: z.string(),
    required_capabilities: z.array(z.string()).default([]),
    chart_requested: z.boolean().default(false),
    is_follow_up: z.boolean().default(false),
    reason_codes: z.array(z.string()).default([]),
  }),
});

const entitiesEvent = z.object({
  ...eventBase,
  type: z.literal("entities.summary"),
  data: z.object({
    entities: z.array(
      z.object({
        kind: z.string(),
        mention: z.string(),
        status: z.enum(["resolved", "ambiguous", "unresolved"]),
        canonical_value: z.string().nullable().optional(),
        candidates: z.array(z.object({ display_value: z.string() })).default([]),
      }),
    ),
    metrics: z.array(z.string()).default([]),
    fiscal_years: z.array(z.number()).default([]),
    fiscal_periods: z.array(z.string()).default([]),
    has_ambiguity: z.boolean().default(false),
  }).loose(),
});

const branchSchema = z.object({
  kind: z.string(),
  branch_id: z.string(),
  depends_on: z.array(z.string()).default([]),
  optional: z.boolean().default(false),
}).loose();

const planEvent = z.object({
  ...eventBase,
  type: z.literal("plan.summary"),
  data: z.object({
    route: z.string(),
    requires_citations: z.boolean(),
    reason_codes: z.array(z.string()).default([]),
    branches: z.array(branchSchema),
  }),
});

const nodeEvent = z.object({
  ...eventBase,
  type: z.literal("node.status"),
  data: z.object({
    step_id: z.string(),
    node: z.string(),
    branch_id: z.string().nullable().optional(),
    status: z.enum(["started", "completed", "failed", "skipped"]),
    attempt: z.number().int().positive(),
    summary: z.string(),
    duration_ms: z.number().nonnegative().nullable().optional(),
  }),
});

const toolEvent = z.object({
  ...eventBase,
  type: z.literal("tool.status"),
  data: z.object({
    branch_id: z.string(),
    kind: z.string(),
    status: z.enum(["started", "completed", "failed", "skipped"]),
    attempts: z.number().int().nonnegative(),
    optional: z.boolean(),
    cache_hit: z.boolean(),
    duration_ms: z.number().nonnegative().nullable().optional(),
    result: z.record(z.string(), z.unknown()).nullable().optional(),
    error_code: z.string().nullable().optional(),
  }),
});

const validationEvent = z.object({
  ...eventBase,
  type: z.literal("validation.summary"),
  data: z.object({
    valid: z.boolean(),
    claim_count: z.number().int().nonnegative(),
    material_claim_count: z.number().int().nonnegative(),
    supported_claim_count: z.number().int().nonnegative(),
    unsupported_claim_count: z.number().int().nonnegative(),
    cited_evidence_count: z.number().int().nonnegative(),
    issue_count: z.number().int().nonnegative(),
    reason_codes: z.array(z.string()),
    repair_attempt: z.number().int().nonnegative(),
    semantic_supported_count: z.number().int().nonnegative(),
    semantic_unsupported_count: z.number().int().nonnegative(),
    semantic_unavailable_count: z.number().int().nonnegative(),
  }),
});

const chartEvent = z.object({
  ...eventBase,
  type: z.literal("chart.ready"),
  data: z.object({
    chart_type: z.string(),
    title: z.string(),
    series_count: z.number().int().nonnegative(),
    point_count: z.number().int().nonnegative(),
    source_count: z.number().int().nonnegative(),
  }),
});

const answerEvent = z.object({
  ...eventBase,
  type: z.literal("answer.token"),
  data: z.object({ index: z.number().int().nonnegative(), delta: z.string() }),
});

const terminalEvent = z.object({
  ...eventBase,
  type: z.literal("run.terminal"),
  data: z.object({ status: statusSchema, error_code: z.string().nullable().optional() }),
});

export const researchEventSchema = z.discriminatedUnion("type", [
  runStatusEvent,
  analysisEvent,
  entitiesEvent,
  planEvent,
  nodeEvent,
  toolEvent,
  validationEvent,
  chartEvent,
  answerEvent,
  terminalEvent,
]);

export type ResearchEvent = z.infer<typeof researchEventSchema>;
export type ResearchEventType = ResearchEvent["type"];

export const researchEventTypes: ResearchEventType[] = [
  "run.status",
  "analysis.summary",
  "entities.summary",
  "plan.summary",
  "node.status",
  "tool.status",
  "validation.summary",
  "chart.ready",
  "answer.token",
  "run.terminal",
];

export function hasTerminalEvent(events: ResearchEvent[]): boolean {
  return events.some((event) => event.type === "run.terminal");
}

export function parseResearchEvent(value: string): ResearchEvent | null {
  try {
    const result = researchEventSchema.safeParse(JSON.parse(value));
    return result.success ? result.data : null;
  } catch {
    return null;
  }
}
