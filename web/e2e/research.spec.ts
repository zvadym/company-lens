import { expect, test, type Route } from "@playwright/test";

const firstRunId = "11111111-1111-4111-8111-111111111111";
const secondRunId = "22222222-2222-4222-8222-222222222222";
const sessionId = "session-11111111-1111-4111-8111-111111111111";
const now = "2026-06-22T12:00:00Z";
const source = {
  evidence_id: "evidence-1",
  exact_url: "https://example.com/cloudflare-10k#risk",
  kind: "section",
  page_end: null,
  page_start: null,
  section_id: "risk",
  source_url: "https://example.com/cloudflare-10k",
  status: "available",
  title: "Cloudflare 10-K risk factors",
};
const citation = {
  claim_ids: ["claim-1"],
  evidence_id: "evidence-1",
  kind: "section",
  label: "Cloudflare 10-K risk factors",
  lineage_refs: [],
  source_urls: [source.exact_url],
  summary: "Cloudflare filing excerpt.",
};
const execution = {
  branches: [],
  errors: [],
  repair_attempts: 0,
  tool_calls_used: 1,
  trajectory: [],
};
const chart = {
  schema_version: "company-lens.chart.v1",
  chart_type: "line",
  title: "Cloudflare revenue growth",
  x_label: "Date",
  series: [{ key: "growth", label: "Cloudflare YoY", unit: "percent" }],
  data: [
    {
      x: "2026-03-31",
      values: { growth: "13.83" },
      source_urls: ["https://example.com/cloudflare-10q"],
    },
  ],
  sources: ["https://example.com/cloudflare-10q"],
};

type MockRun = {
  run_id: string;
  session_id: string;
  status: "completed" | "queued";
  question: string;
  result: {
    agent_status: "completed";
    answer: string;
    citations: typeof citation[];
    chart: typeof chart | null;
    execution: typeof execution;
    sources: typeof source[];
    warnings: [];
  };
  queued_at: string;
  started_at: string;
  completed_at: string;
  deadline_at: string;
};

test("submits a question and renders streamed execution detail", async ({ page }) => {
  const posts: unknown[] = [];
  const runs: Record<string, MockRun> = {};
  const runFromRoute = (route: Route) => {
    const match = route.request().url().match(/\/api\/v1\/research\/([^/?]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  };

  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: (value: string) => {
          window.localStorage.setItem("copied-answer", value);
          return Promise.resolve();
        },
      },
    });
  });

  await page.route("**/api/v1/companies", (route) =>
    route.fulfill({ json: { items: [], total: 0 } }),
  );
  await page.route("**/api/v1/research?**", (route) => {
    if (route.request().url().includes("/events")) return route.fallback();
    return route.fulfill({
      json: {
        items: Object.values(runs),
        total: Object.values(runs).length,
      },
    });
  });
  await page.route("**/api/v1/research", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = JSON.parse(route.request().postData() ?? "{}") as {
      question: string;
      session_id?: string;
    };
    posts.push(body);
    const runId = Object.keys(runs).length === 0 ? firstRunId : secondRunId;
    runs[runId] = {
      run_id: runId,
      session_id: sessionId,
      status: "completed",
      question: body.question,
      result: runId === firstRunId
        ? {
            agent_status: "completed",
            answer: "Cloudflare cites this filing evidence [evidence-1].",
            citations: [citation],
            chart,
            execution,
            sources: [source],
            warnings: [],
          }
        : {
            agent_status: "completed",
            answer: "Margins answer.",
            citations: [],
            chart: null,
            execution,
            sources: [],
            warnings: [],
          },
      queued_at: now,
      started_at: now,
      completed_at: now,
      deadline_at: now,
    };
    return route.fulfill({
      status: 202,
      json: {
        run_id: runId,
        session_id: sessionId,
        status: "queued",
        run_url: `/api/v1/research/${runId}`,
        events_url: `/api/v1/research/${runId}/events`,
        sources_url: `/api/v1/research/${runId}/sources`,
      },
    });
  });
  await page.route("**/api/v1/research/*/sources", (route) => {
    const runId = runFromRoute(route);
    return route.fulfill({ json: { run_id: runId, sources: runs[runId]?.result.sources ?? [] } });
  });
  await page.route("**/api/v1/research/*/events?**", (route) => {
    const runId = runFromRoute(route);
    const events = [
      {
        id: 1,
        schema_version: "2",
        run_id: runId,
        type: "analysis.summary",
        occurred_at: now,
        data: {
          route: "structured_only",
          required_capabilities: ["financial_facts"],
          chart_requested: false,
          is_follow_up: false,
          reason_codes: ["financial_metric_requested"],
        },
      },
      {
        id: 2,
        schema_version: "2",
        run_id: runId,
        type: "run.terminal",
        occurred_at: now,
        data: { status: "completed", error_code: null },
      },
    ];
    const body = events
      .map((event) => `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`)
      .join("");
    return route.fulfill({ status: 200, contentType: "text/event-stream", body });
  });
  await page.route("**/api/v1/research/*", (route) => {
    if (route.request().url().includes("/events") || route.request().url().includes("/sources")) {
      return route.fallback();
    }
    const runId = runFromRoute(route);
    return route.fulfill({ json: runs[runId] });
  });

  await page.goto("/research/new");
  await page.getByRole("button", { name: /compare cloudflare revenue growth/i }).click();
  await expect(page).toHaveURL(new RegExp(`/research/${sessionId}\\?run=${firstRunId}$`));
  expect(posts[0]).toEqual({
    question: "Compare Cloudflare revenue growth over the last eight quarters.",
  });
  await expect(page.getByRole("navigation", { name: "Research history" })).toContainText(
    "Compare Cloudflare revenue growth",
  );
  await expect(page.getByText(/Intent · structured only/i)).toHaveCount(0);
  await expect(page.getByText("CompanyLens synthesis")).toHaveCount(0);
  await expect(page.locator(".message-assistant").first().locator(".message-meta")).toContainText("Jun 22");
  await page.locator(".message-assistant").first()
    .getByRole("button", { name: /copy answer text/i })
    .click();
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem("copied-answer")))
    .toBe("Cloudflare cites this filing evidence [evidence-1].");
  await page.locator(".message-assistant").first()
    .getByRole("button", { name: /show methodology/i })
    .click();
  await expect(page.getByText(/Intent · structured only/i)).toBeVisible();
  await expect(page.getByText("financial_metric_requested", { exact: true })).toBeVisible();
  await expect(page.getByText(/Run 1/i)).toHaveCount(0);

  await page.getByLabel("Research question").fill("What about margins?");
  await page.getByRole("button", { name: "Start research" }).click();

  await expect(page).toHaveURL(new RegExp(`/research/${sessionId}\\?run=${secondRunId}$`));
  expect(posts[1]).toEqual({ question: "What about margins?", session_id: sessionId });
  await expect(page.getByText("What about margins?")).toBeVisible();
  await expect(
    page.locator(".thread-root")
      .getByText("Compare Cloudflare revenue growth over the last eight quarters.", {
        exact: true,
      }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cloudflare revenue growth" })).toBeVisible();
  await page.locator(".message-assistant").first()
    .getByRole("link", { name: /show source 1/i })
    .click();
  await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
  await expect(page.getByText("Cloudflare 10-K risk factors")).toBeVisible();
});
