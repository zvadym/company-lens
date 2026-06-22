import type { ResearchCitation, ResearchSource } from "@/api/types";

export type EvidenceSourceGroup = {
  evidenceId: string;
  evidenceIds: string[];
  kind: ResearchSource["kind"];
  sources: ResearchSource[];
};

export type CalculationPoint = {
  label: string;
  value: string;
};

export type SourcePresentation = {
  title: string;
  summary: string | null;
  statusLabel: string | null;
  calculationPoints: CalculationPoint[];
};

const operationLabels: Record<string, string> = {
  correlation: "Correlation",
  difference: "Difference",
  percent_change: "Percentage change",
  ratio: "Ratio",
  year_over_year_growth: "Year-over-year growth",
};

export function groupEvidenceSources(
  sources: ResearchSource[],
  citations: ResearchCitation[] = [],
): EvidenceSourceGroup[] {
  const groupsByEvidenceId = new Map<string, EvidenceSourceGroup>();
  for (const source of sources) {
    const existing = groupsByEvidenceId.get(source.evidence_id);
    if (existing) {
      if (!existing.sources.some((item) => item.exact_url === source.exact_url)) {
        existing.sources.push(source);
      }
      continue;
    }
    groupsByEvidenceId.set(source.evidence_id, {
      evidenceId: source.evidence_id,
      evidenceIds: [source.evidence_id],
      kind: source.kind,
      sources: [source],
    });
  }

  const citationById = new Map(citations.map((citation) => [citation.evidence_id, citation]));
  const groupedByContent = new Map<string, EvidenceSourceGroup>();
  for (const group of groupsByEvidenceId.values()) {
    const citation = citationById.get(group.evidenceId);
    // Only merge across evidence IDs when the API provides the complete citation summary.
    // SourcePreview.title is truncated and therefore unsafe as a deduplication key.
    const contentKey = citation
      ? `${group.kind}:${cleanText(citation.summary).toLocaleLowerCase("en")}`
      : `evidence:${group.evidenceId}`;
    const existing = groupedByContent.get(contentKey);
    if (!existing) {
      groupedByContent.set(contentKey, group);
      continue;
    }
    existing.evidenceIds.push(...group.evidenceIds);
    for (const source of group.sources) {
      if (!existing.sources.some((item) => item.exact_url === source.exact_url)) {
        existing.sources.push(source);
      }
    }
  }
  return [...groupedByContent.values()];
}

export function sourceLinkLabel(
  source: ResearchSource,
  sourceIndex: number,
  sourceCount: number,
): string {
  if (sourceCount === 1) return "Open source";
  const periodYear = `${source.evidence_id} ${source.exact_url}`.match(/(?:cloud-|period[=/])(20\d{2})\d{4}/)?.[1];
  return periodYear ? `FY ${periodYear} filing` : `Open filing ${sourceIndex + 1}`;
}

function cleanText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function truncate(value: string, maximum = 280): string {
  const clean = cleanText(value);
  return clean.length > maximum ? `${clean.slice(0, maximum - 1).trimEnd()}…` : clean;
}

function calculationOperation(summary: string): string | null {
  return summary.match(/^([a-z][a-z0-9_]+)\s*:/)?.[1] ?? null;
}

function calculationPoints(summary: string, operation: string | null): CalculationPoint[] {
  const points: CalculationPoint[] = [];
  const pattern = /'label':\s*'([^']+)',\s*'value':\s*'([^']+)',\s*'observed_at':\s*'([^']+)'/g;
  for (const match of summary.matchAll(pattern)) {
    const [, rawLabel, rawValue, observedAt] = match;
    if (!rawLabel || !rawValue || !observedAt) continue;
    const numericValue = Number(rawValue);
    const isGrowth = operation === "year_over_year_growth";
    const value = Number.isFinite(numericValue)
      ? `${numericValue.toFixed(isGrowth ? 1 : 2)}${isGrowth ? "%" : ""}`
      : rawValue;
    points.push({ label: observedAt.slice(0, 4) || cleanText(rawLabel), value });
  }
  return points;
}

function documentTitle(source: ResearchSource): string {
  const sectionName = source.evidence_id.split(":").at(-1);
  if (source.evidence_id.startsWith("section:")) {
    if (sectionName === "business") return "Item 1 · Business";
    if (sectionName === "competition") return "Risk factors · Competition and execution";
    if (sectionName === "liquidity") return "Liquidity and capital resources";
  }
  const firstLine = source.title.split("\n").map((line) => line.trim()).find(Boolean);
  return truncate(firstLine || "Supporting document", 90);
}

function financialFactPresentation(summary: string): Pick<SourcePresentation, "title" | "summary"> {
  const match = cleanText(summary).match(
    /^(.+?):\s*([+-]?\d+(?:\.\d+)?)\s+(\S+)\s+at\s+(\d{4})-(\d{2})-(\d{2})$/,
  );
  if (!match) return { title: "Reported financial fact", summary: truncate(summary) };
  const [, label, rawValue, unit, year, month, day] = match;
  const value = Number(rawValue);
  const currencyUnits = new Set(["USD", "EUR", "GBP", "JPY", "CAD", "AUD"]);
  const compactValue = currencyUnits.has(unit || "")
    ? new Intl.NumberFormat("en", {
        style: "currency",
        currency: unit,
        notation: "compact",
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }).format(value)
    : `${new Intl.NumberFormat("en", {
        notation: "compact",
        maximumFractionDigits: 2,
      }).format(value)} ${unit}`;
  const period = month === "12" && day === "31"
    ? `FY ${year}`
    : new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(`${year}-${month}-${day}T00:00:00Z`));
  return {
    title: label || "Reported financial fact",
    summary: `${compactValue} · ${period}`,
  };
}

export function presentEvidenceSource(
  group: EvidenceSourceGroup,
  citation: ResearchCitation | undefined,
): SourcePresentation {
  const source = group.sources[0];
  if (!source) {
    return { title: "Evidence", summary: null, statusLabel: null, calculationPoints: [] };
  }
  const summary = citation?.summary || source.title;
  const inaccessible = group.sources.some(
    (item) => item.status === "invalid" || item.status === "inaccessible",
  );

  if (group.kind === "calculation") {
    const operation = calculationOperation(summary);
    const points = calculationPoints(summary, operation);
    const inputCount = citation?.lineage_refs.length ?? 0;
    return {
      title: operation ? operationLabels[operation] ?? operation.replaceAll("_", " ") : "Calculation",
      summary: inputCount > 0
        ? `Derived from ${inputCount} evidence record${inputCount === 1 ? "" : "s"}.`
        : "Derived from cited evidence.",
      statusLabel: "derived",
      calculationPoints: points,
    };
  }

  if (group.kind === "financial_fact") {
    const fact = financialFactPresentation(summary);
    return {
      ...fact,
      statusLabel: inaccessible ? "link unavailable" : null,
      calculationPoints: [],
    };
  }

  return {
    title: group.kind === "document" ? documentTitle(source) : truncate(source.title, 90),
    summary: truncate(summary),
    statusLabel: inaccessible ? "link unavailable" : null,
    calculationPoints: [],
  };
}
