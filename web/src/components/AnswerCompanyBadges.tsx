import type { ResearchResult } from "@/api/types";

type AnswerCompany = ResearchResult["answer_companies"][number];

type AnswerCompanyBadgesProps = {
  companies?: readonly AnswerCompany[];
};

function companyLabel(company: AnswerCompany): string {
  const ticker = company.primary_ticker?.trim();
  if (ticker) return ticker;
  return company.display_name;
}

function companyAccessibleName(company: AnswerCompany): string {
  const ticker = company.primary_ticker?.trim();
  if (ticker && company.display_name !== ticker) return `${company.display_name} (${ticker})`;
  return company.display_name;
}

function CompanyBadge({ company }: { company: AnswerCompany }) {
  const label = companyLabel(company);
  const accessibleName = companyAccessibleName(company);
  const body = (
    <>
      <span className="answer-company-ticker">{label}</span>
      {company.display_name !== label ? (
        <span className="answer-company-name">{company.display_name}</span>
      ) : null}
    </>
  );

  if (company.profile_url) {
    return (
      <a
        className="answer-company-badge"
        href={company.profile_url}
        target="_blank"
        rel="noreferrer"
        aria-label={`Company ${accessibleName}`}
      >
        {body}
      </a>
    );
  }

  return (
    <span className="answer-company-badge" aria-label={`Company ${accessibleName}`}>
      {body}
    </span>
  );
}

export function AnswerCompanyBadges({ companies = [] }: AnswerCompanyBadgesProps) {
  if (companies.length === 0) return null;

  return (
    <div className="answer-companies" aria-label="Answer companies">
      {companies.map((company) => (
        <CompanyBadge
          key={company.id ?? company.primary_ticker ?? company.display_name}
          company={company}
        />
      ))}
    </div>
  );
}
