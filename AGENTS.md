# Repository Instructions

- For development data and database checks, always use the Docker dev stack started by
  `make start-dev-docker`; do not treat local files such as `company_lens.db` as the
  source of truth for dev.
- Before running development commands or checking the dev database, verify that `.env`
  exists. It must be present and contain all required keys. If `.env` is missing, stop
  and ask the user to create it.
- When implementing a GitHub issue, create a new branch named `ID/short-description`.
- Every commit for issue work must reference the issue as `#ID`.
- Add succinct code comments for non-obvious logic, invariants, fallbacks, state transitions,
  and domain-specific assumptions. Avoid comments that merely restate what the code already says.
