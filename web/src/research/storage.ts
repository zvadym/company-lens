import type { ResearchEvent } from "./events";

const SESSION_KEY = "company-lens.session.v1";
const TRACE_PREFIX = "company-lens.trace.v1:";
const MAX_STORED_EVENTS = 500;

export function getSessionId(): string {
  const existing = window.localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const created = `web-${crypto.randomUUID()}`;
  window.localStorage.setItem(SESSION_KEY, created);
  return created;
}

export function loadTrace(runId: string): ResearchEvent[] {
  try {
    const raw = window.localStorage.getItem(`${TRACE_PREFIX}${runId}`);
    if (!raw) return [];
    const values: unknown = JSON.parse(raw);
    if (!Array.isArray(values)) return [];
    return values.filter((value): value is ResearchEvent => {
      return typeof value === "object" && value !== null && "id" in value;
    });
  } catch {
    return [];
  }
}

export function storeTrace(runId: string, events: ResearchEvent[]): void {
  try {
    window.localStorage.setItem(
      `${TRACE_PREFIX}${runId}`,
      JSON.stringify(events.slice(-MAX_STORED_EVENTS)),
    );
  } catch {
    // Storage is a recovery optimization. The live stream remains authoritative.
  }
}
