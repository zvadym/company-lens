import type { components } from "./schema";

export type ResearchAccepted = components["schemas"]["ResearchAccepted"];
export type ResearchRun = components["schemas"]["ResearchRunResponse"];
export type ResearchRunList = components["schemas"]["ResearchRunListResponse"];
export type ResearchStatus = components["schemas"]["ResearchRunStatus"];
export type ResearchResult = components["schemas"]["ResearchResult"];
export type ResearchSource = components["schemas"]["SourcePreview"];
export type ResearchCitation = components["schemas"]["ResearchCitationOutput"];
export type ChartSpecification = components["schemas"]["ChartSpecification"];
export type Company = components["schemas"]["CompanyOutput"];
export type FeedbackRating = components["schemas"]["FeedbackRequest"]["rating"];

export const terminalStatuses = new Set<ResearchStatus>([
  "completed",
  "partial",
  "abstained",
  "failed",
  "cancelled",
  "timed_out",
]);

export function isTerminal(status: ResearchStatus): boolean {
  return terminalStatuses.has(status);
}
