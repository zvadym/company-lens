import { expect, test } from "@playwright/test";

const runId = "11111111-1111-4111-8111-111111111111";
const now = "2026-06-22T12:00:00Z";

test("submits a question and renders streamed execution detail", async ({ page }) => {
  let started = false;
  await page.route("**/api/v1/companies", (route) =>
    route.fulfill({ json: { items: [], total: 0 } }),
  );
  await page.route("**/api/v1/research?**", (route) => {
    if (route.request().url().includes("/events")) return route.fallback();
    return route.fulfill({
      json: {
        items: started
          ? [{
              run_id: runId,
              session_id: "web-test",
              status: "completed",
              question: "Compare Cloudflare revenue growth over the last eight quarters.",
              result: null,
              queued_at: now,
              started_at: now,
              completed_at: now,
              deadline_at: now,
            }]
          : [],
        total: started ? 1 : 0,
      },
    });
  });
  await page.route("**/api/v1/research", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    started = true;
    return route.fulfill({
      status: 202,
      json: {
        run_id: runId,
        session_id: "web-test",
        status: "queued",
        run_url: `/api/v1/research/${runId}`,
        events_url: `/api/v1/research/${runId}/events`,
        sources_url: `/api/v1/research/${runId}/sources`,
      },
    });
  });
  await page.route(`**/api/v1/research/${runId}`, (route) =>
    route.fulfill({
      json: {
        run_id: runId,
        session_id: "web-test",
        status: "completed",
        question: "Compare Cloudflare revenue growth over the last eight quarters.",
        result: null,
        queued_at: now,
        started_at: now,
        completed_at: now,
        deadline_at: now,
      },
    }),
  );
  await page.route(`**/api/v1/research/${runId}/sources`, (route) =>
    route.fulfill({ json: { run_id: runId, sources: [] } }),
  );
  await page.route(`**/api/v1/research/${runId}/events?**`, (route) => {
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

  await page.goto("/research/new");
  await page.getByRole("button", { name: /compare cloudflare revenue growth/i }).click();
  await expect(page).toHaveURL(new RegExp(`/research/${runId}$`));
  await expect(page.getByText(/Intent · structured only/i)).toBeVisible();
  await expect(page.getByText(/financial metric requested/i)).toBeVisible();
});
