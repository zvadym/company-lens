import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnswerCompanyBadges } from "./AnswerCompanyBadges";

afterEach(cleanup);

describe("AnswerCompanyBadges", () => {
  it("renders linked ticker badges when a company profile URL is available", () => {
    render(
      <AnswerCompanyBadges
        companies={[
          {
            id: "11111111-1111-4111-8111-111111111111",
            display_name: "Cloudflare",
            legal_name: "Cloudflare, Inc.",
            cik: "1477333",
            primary_ticker: "NET",
            exchange: "NYSE",
            profile_url: "https://www.sec.gov/edgar/browse/?CIK=1477333",
          },
        ]}
      />,
    );

    const link = screen.getByRole("link", { name: "Company Cloudflare (NET)" });
    expect(link).toBeVisible();
    expect(link).toHaveAttribute("href", "https://www.sec.gov/edgar/browse/?CIK=1477333");
    expect(screen.getByText("NET")).toBeVisible();
    expect(screen.getByText("Cloudflare")).toBeVisible();
  });

  it("renders static badges when no company route is available", () => {
    render(
      <AnswerCompanyBadges
        companies={[
          {
            id: "33333333-3333-4333-8333-333333333333",
            display_name: "Netflix",
            legal_name: "Netflix, Inc.",
            cik: "1065280",
            primary_ticker: "NFLX",
            exchange: "NASDAQ",
            profile_url: null,
          },
        ]}
      />,
    );

    expect(screen.queryByRole("link", { name: /netflix/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Company Netflix (NFLX)")).toBeVisible();
  });
});
