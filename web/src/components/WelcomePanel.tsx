import { ThreadPrimitive } from "@assistant-ui/react";
import { ArrowUp, Sparkles } from "lucide-react";

import { useResearch } from "@/research/context";

const examplePrompts = [
  {
    kind: "Chart",
    prompt: "Show Cloudflare revenue growth over the last four quarters.",
  },
  {
    kind: "Compare",
    prompt: "Compare Cloudflare and Datadog revenue growth over the last eight quarters.",
  },
  {
    kind: "Risks",
    prompt: "How did Cloudflare risk factors change from 2024 to 2025?",
  },
  {
    kind: "Macro",
    prompt: "Plot Cloudflare revenue growth against the federal funds rate.",
  },
];

export function WelcomePanel() {
  const { companies } = useResearch();
  const universe = companies
    .slice(0, 5)
    .map((company) => company.primary_ticker ?? company.display_name)
    .join(" · ");

  return (
    <ThreadPrimitive.Empty>
      <section className="welcome">
        <div className="welcome-kicker"><Sparkles size={14} /> Evidence-first company intelligence</div>
        <h1>Research that shows<br /><em>its work.</em></h1>
        <p>
          Ask a public-company question. CompanyLens will select the data path, expose every safe
          execution step, and validate the answer against its evidence.
        </p>
        {universe ? <div className="company-universe">Coverage · {universe}</div> : null}
        <div className="prompt-grid" aria-label="Example research questions">
          {examplePrompts.map((example) => (
            <ThreadPrimitive.Suggestion
              key={example.prompt}
              prompt={example.prompt}
              send
              className="prompt-card"
            >
              <span>{example.kind}</span>
              <strong>{example.prompt}</strong>
              <ArrowUp size={16} />
            </ThreadPrimitive.Suggestion>
          ))}
        </div>
      </section>
    </ThreadPrimitive.Empty>
  );
}
