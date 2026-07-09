# Repository Instructions

- For development data and database checks, always use the Docker dev stack started by
  `make start-dev-docker`; do not treat local files such as `company_lens.db` as the
  source of truth for dev.
- Before running development commands or checking the dev database, verify that `.env`
  exists. It must be present and contain all required keys. If `.env` is missing, stop
  and ask the user to create it.
- When implementing a GitHub issue, create a new branch named `ID/short-description`.
- Every commit for issue work must reference the issue as `#ID`.
- Before committing, run the local quality gate with `make check`. Do not commit if it
  fails; if the check cannot be run locally, state the reason explicitly before committing.
- Add succinct code comments for non-obvious logic, invariants, fallbacks, state transitions,
  and domain-specific assumptions. Avoid comments that merely restate what the code already says.
- When changing a file longer than 250 lines, first try to split cohesive logic into smaller
  files. If splitting would make the code less safe or less readable, note the reason explicitly.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
