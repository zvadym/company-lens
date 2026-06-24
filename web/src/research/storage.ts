import type { ResearchEvent } from "./events";
import type { ResearchStatus } from "@/api/types";

const LEGACY_SESSION_KEY = "company-lens.session.v1";
const RESEARCH_INDEX_KEY = "company-lens.research-index.v1";
const TRACE_PREFIX = "company-lens.trace.v1:";
const MAX_STORED_EVENTS = 500;
const MAX_STORED_RESEARCH = 100;

export type StoredResearch = {
  researchId: string;
  title: string;
  lastRunId: string | null;
  lastQuestion: string;
  status: ResearchStatus;
  createdAt: string;
  updatedAt: string;
};

type StoredResearchInput = {
  researchId: string;
  title?: string;
  lastRunId?: string | null;
  lastQuestion?: string;
  status?: ResearchStatus;
  createdAt?: string;
  updatedAt?: string;
};

const DEFAULT_STATUS: ResearchStatus = "completed";

export function getSessionId(): string {
  const existing = window.localStorage.getItem(LEGACY_SESSION_KEY);
  if (existing) return existing;
  const created = `web-${crypto.randomUUID()}`;
  window.localStorage.setItem(LEGACY_SESSION_KEY, created);
  return created;
}

export function researchTitleFromQuestion(question: string): string {
  const cleaned = question.trim().replace(/\s+/g, " ");
  if (!cleaned) return "Untitled research";
  return cleaned.length > 80 ? `${cleaned.slice(0, 77)}...` : cleaned;
}

export function loadResearchIndex(): StoredResearch[] {
  const values = readResearchIndex();
  const legacy = window.localStorage.getItem(LEGACY_SESSION_KEY);
  if (legacy && !values.some((item) => item.researchId === legacy)) {
    const now = new Date().toISOString();
    values.push({
      researchId: legacy,
      title: "Legacy research",
      lastRunId: null,
      lastQuestion: "",
      status: DEFAULT_STATUS,
      createdAt: now,
      updatedAt: now,
    });
    writeResearchIndex(values);
  }
  return sortResearchIndex(values);
}

export function upsertResearchIndex(input: StoredResearchInput): StoredResearch[] {
  const now = new Date().toISOString();
  const values = readResearchIndex();
  const existing = values.find((item) => item.researchId === input.researchId);
  const lastQuestion = input.lastQuestion ?? existing?.lastQuestion ?? "";
  const updated: StoredResearch = {
    researchId: input.researchId,
    title: input.title ?? existing?.title ?? researchTitleFromQuestion(lastQuestion),
    lastRunId: input.lastRunId !== undefined ? input.lastRunId : existing?.lastRunId ?? null,
    lastQuestion,
    status: input.status ?? existing?.status ?? DEFAULT_STATUS,
    createdAt: input.createdAt ?? existing?.createdAt ?? input.updatedAt ?? now,
    updatedAt: input.updatedAt ?? now,
  };
  const next = [updated, ...values.filter((item) => item.researchId !== input.researchId)];
  writeResearchIndex(next);
  return sortResearchIndex(next);
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

function readResearchIndex(): StoredResearch[] {
  try {
    const raw = window.localStorage.getItem(RESEARCH_INDEX_KEY);
    if (!raw) return [];
    const values: unknown = JSON.parse(raw);
    if (!Array.isArray(values)) return [];
    return values.filter(isStoredResearch);
  } catch {
    return [];
  }
}

function writeResearchIndex(values: StoredResearch[]): void {
  try {
    window.localStorage.setItem(
      RESEARCH_INDEX_KEY,
      JSON.stringify(sortResearchIndex(values).slice(0, MAX_STORED_RESEARCH)),
    );
  } catch {
    // The index improves anonymous history only. API state remains authoritative.
  }
}

function sortResearchIndex(values: StoredResearch[]): StoredResearch[] {
  return [...values].toSorted((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

function isStoredResearch(value: unknown): value is StoredResearch {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Partial<StoredResearch>;
  return (
    typeof item.researchId === "string"
    && typeof item.title === "string"
    && (typeof item.lastRunId === "string" || item.lastRunId === null)
    && typeof item.lastQuestion === "string"
    && typeof item.status === "string"
    && typeof item.createdAt === "string"
    && typeof item.updatedAt === "string"
  );
}
