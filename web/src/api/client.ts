import createClient from "openapi-fetch";

import type { paths } from "./schema";
import type { FeedbackRating } from "./types";

const api = createClient<paths>({ baseUrl: "" });

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorMessage(error: unknown): { code: string; message: string } {
  if (typeof error === "object" && error !== null && "error" in error) {
    const detail = (error as { error?: unknown }).error;
    if (typeof detail === "object" && detail !== null) {
      const value = detail as { code?: unknown; message?: unknown };
      if (typeof value.code === "string" && typeof value.message === "string") {
        return { code: value.code, message: value.message };
      }
    }
  }
  return { code: "request_failed", message: "The API request could not be completed." };
}

function unwrap<T>(data: T | undefined, error: unknown, response: Response): T {
  if (data !== undefined) return data;
  const detail = errorMessage(error);
  throw new ApiError(response.status, detail.code, detail.message);
}

export async function startResearch(question: string, researchId?: string | null) {
  const { data, error, response } = await api.POST("/api/v1/research", {
    body: { question, session_id: researchId ?? undefined },
  });
  return unwrap(data, error, response);
}

export async function getResearch(runId: string) {
  const { data, error, response } = await api.GET("/api/v1/research/{run_id}", {
    params: { path: { run_id: runId } },
  });
  return unwrap(data, error, response);
}

export async function listResearchRuns(researchId: string, limit = 50) {
  const { data, error, response } = await api.GET("/api/v1/research", {
    params: { query: { session_id: researchId, limit } },
  });
  return unwrap(data, error, response);
}

export async function getSources(runId: string) {
  const { data, error, response } = await api.GET(
    "/api/v1/research/{run_id}/sources",
    { params: { path: { run_id: runId } } },
  );
  return unwrap(data, error, response);
}

export async function cancelResearch(runId: string) {
  const { data, error, response } = await api.DELETE("/api/v1/research/{run_id}", {
    params: { path: { run_id: runId } },
  });
  return unwrap(data, error, response);
}

export async function submitFeedback(runId: string, rating: FeedbackRating) {
  const { data, error, response } = await api.POST("/api/v1/feedback", {
    body: { run_id: runId, rating },
  });
  return unwrap(data, error, response);
}

export async function listCompanies() {
  const { data, error, response } = await api.GET("/api/v1/companies");
  return unwrap(data, error, response);
}
