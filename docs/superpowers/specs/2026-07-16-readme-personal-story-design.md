# Personal-Story README Design

## Goal

Rewrite the root README so a non-technical reader can quickly understand why CompanyLens exists,
what the project explores, and how evaluation influenced its development. The README should feel
like a concise portfolio story rather than a product brochure or an architecture reference.

## Audience and Tone

- Write in English and use the first person when explaining motivation and learning goals.
- Assume the reader understands what an AI assistant is but does not know retrieval terminology.
- Prefer short explanations and concrete outcomes over implementation details.
- Keep the tone curious, honest, and personal without underselling the engineering work.

## README Structure

1. **Introduction** — explain that CompanyLens is a learning project built to understand how to
   create, improve, and evaluate an AI research agent for public-company questions.
2. **What I explored** — explain RAG, re-ranking, and query rewriting in one plain-language sentence
   each.
3. **What the agent does** — summarize how it combines company filings, structured financial facts,
   macroeconomic data, calculations, charts, and verifiable citations.
4. **Evaluation and Langfuse** — explain why building the agent was only half the work and how
   repeatable datasets, traces, and scores help compare changes, diagnose failures, and catch
   regressions.
5. **Technology** — list the principal technologies compactly: Python, FastAPI, LangGraph,
   PostgreSQL with pgvector, OpenAI models, Langfuse, React, and Docker.
6. **Screenshot and technical deep dives** — retain the product screenshot and link detailed
   implementation material instead of reproducing it in the README.
7. **Local development and license** — preserve concise setup instructions and licensing details for
   technical readers.

## Accuracy Boundaries

- Describe RAG and adaptive retrieval as implemented capabilities.
- Describe re-ranking as implemented but optional; it is disabled by default locally.
- Describe query rewriting as the next planned retrieval experiment, not as a current capability.
- Describe Langfuse as part of the implemented evaluation workflow: repository-owned golden cases
  are synchronized to datasets, runs publish item-level and aggregate scores, and results remain
  inspectable alongside local artifacts.
- Do not imply that a few successful demos prove agent quality.
- Avoid presenting CompanyLens as a production financial-advice product.

## Documentation Changes

- Rewrite `README.md` around the personal learning story.
- Keep `docs/portfolio/retrieval-and-reranking.md` as the technical source for retrieval, optional
  re-ranking, and planned query rewriting.
- Add `docs/portfolio/evaluation-and-langfuse.md` as a focused technical deep dive derived from the
  implemented evaluation workflow.
- Retain links to the existing agent graph, hybrid walkthrough, API, and operations documentation.

## Validation

- Confirm every README link resolves to a repository file.
- Check that README terminology matches the current implementation and linked deep dives.
- Keep the opening understandable without reading any technical document.
- Run the repository quality gate before committing.
