import type { ChartSpecification } from "@/api/types";

type ChartSeriesItem = ChartSpecification["series"][number];

export function formatChartValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatChartValue).join(" - ");
  if (value == null) return "";
  if (typeof value !== "number" && typeof value !== "string") return "";
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return typeof value === "string" ? value : "";
  return new Intl.NumberFormat("en", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
  }).format(numericValue);
}

function roundedChartValue(value: string | number): number {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return numericValue;
  return Math.round(numericValue * 100) / 100;
}

export function displaySeriesLabel(
  chart: ChartSpecification,
  series: ChartSeriesItem,
  index: number,
): string {
  const label = series.label.trim();
  if (label && label !== "year_over_year_growth") return label.replaceAll("_", " ");
  const titleParts = chart.title.split(/\s+(?:v(?:s\.?|ersus)|against)\s+/i);
  const titleCompany = titleParts[index]
    ?.replace(/\brevenue\b/gi, "")
    .replace(/\bgrowth\b/gi, "")
    .trim();
  if (titleCompany) return `${titleCompany} YoY`;
  const keyCompany = series.key
    .replace(/^calc_/, "")
    .replace(/_?growth$/, "")
    .replace(/_?revenue$/, "")
    .replaceAll("_", " ")
    .trim();
  return keyCompany ? `${titleCase(keyCompany)} YoY` : "YoY growth";
}

function titleCase(value: string): string {
  return value.replace(/\b\w/g, (character) => character.toLocaleUpperCase("en"));
}

export function chartData(chart: ChartSpecification) {
  return chart.data.map((point) => {
    const values = Object.fromEntries(
      Object.entries(point.values).map(([key, value]) => [key, roundedChartValue(value)]),
    );
    return { x: point.x, ...values };
  });
}
