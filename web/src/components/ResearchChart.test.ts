import { describe, expect, it } from "vitest";

import type { ChartSpecification } from "@/api/types";

import { chartData, displaySeriesLabel, formatChartValue } from "./researchChartFormatting";

const chart: ChartSpecification = {
  schema_version: "company-lens.chart.v1",
  chart_type: "line",
  title: "Cloudflare Revenue Growth vs Netflix Revenue Growth",
  x_label: "Date",
  series: [
    { key: "calc_clf_growth", label: "year_over_year_growth", unit: "percent" },
    { key: "calc_nflx_growth", label: "year_over_year_growth", unit: "percent" },
  ],
  data: [
    {
      x: "2026-03-31",
      values: {
        calc_clf_growth: "33.53628881601880243045626370",
        calc_nflx_growth: "16.19072578530126860973663450",
      },
      source_urls: ["https://example.test/source"],
    },
  ],
  sources: ["https://example.test/source"],
};

describe("ResearchChart formatting", () => {
  it("derives useful labels for legacy generic YoY series", () => {
    expect(displaySeriesLabel(chart, chart.series[0]!, 0)).toBe("Cloudflare YoY");
    expect(displaySeriesLabel(chart, chart.series[1]!, 1)).toBe("Netflix YoY");
    expect(
      displaySeriesLabel(
        { ...chart, title: "Cloudflare Revenue Growth against Netflix Revenue Growth" },
        chart.series[1]!,
        1,
      ),
    ).toBe("Netflix YoY");
  });

  it("formats chart values to two decimal places", () => {
    expect(formatChartValue("33.53628881601880243045626370")).toBe("33.54");
    expect(formatChartValue("16.1")).toBe("16.1");
    expect(chartData(chart)[0]).toMatchObject({
      calc_clf_growth: 33.54,
      calc_nflx_growth: 16.19,
    });
  });
});
