# Contract: Manual Evaluation Workflow

## Trigger

The workflow remains `workflow_dispatch`. The Actions UI provides the Run workflow button and ref
selector.

Inputs:

| Input | Type | Required | Default | Rules |
|---|---|---:|---|---|
| `dataset_scope` | choice | yes | `all` | `all`, `core`, or `follow_up` |
| `max_cases` | string/integer | yes | `100` | Positive; applied per dataset |
| `model` | string | yes | current testing model | Passed to planning/answer/repair settings |
| `max_tool_calls` | string/integer | yes | `10` | Positive and recorded in manifest |
| `pr_number` | string/integer | no | empty | Positive repository PR number when supplied |
| `sec_user_agent` | string | yes | current testing value | Required by SEC ingestion |

Permissions:

```yaml
contents: read
pull-requests: write
actions: read
```

The job uses the `Testing` environment and requires OpenAI and Langfuse credentials plus
`COMPANY_LENS_LANGFUSE_PROJECT_ID`. FRED remains required only when selected cases need macro data.

## Step Ordering

1. Checkout selected ref and install the project with the repository's pinned Python range.
2. Normalize secrets without printing values.
3. Resolve the project associated with the Langfuse project-scoped key and require its ID to match
   `COMPANY_LENS_LANGFUSE_PROJECT_ID` before any remote write or provider call; then preflight other
   provider access.
4. Start PostgreSQL service, run migrations, and initialize research persistence.
5. Resolve `dataset_scope` to a fixed allowlist of repository paths.
6. Run `company-lens run-evaluation`, pass `--repository "$GITHUB_REPOSITORY"` with `--pr-number` when
   supplied so the journal records the exact pending reporting target, and capture exit code without
   ending the job.
7. When final JSON or Markdown is missing but a valid journal exists, run `recover-evaluation`.
8. When `pr_number` is supplied, call `report-evaluation-pr` with the validated execution artifact,
   recovery journal, expected PR head SHA, artifact URL, and Langfuse links. The command terminalizes
   only reporting state in the journal, including when evaluation preflight failed before any
   provider-backed case and the summary contains only sanitized unavailable/failure markers.
9. Upload the complete, reporting-terminal artifact directory with `if: always()`.
10. Exit with the captured orchestrator code; recovery or reporting failure uses infrastructure exit
    code `2`.

## Canonical PR Comment

Hidden marker:

```html
<!-- company-lens-evaluation-foundation -->
```

Before reading or writing comments, the workflow verifies that the PR belongs to the current
repository and that its current head SHA exactly matches the evaluated `github.sha`. A mismatch is a
reporting infrastructure error. The workflow then searches comments authored by
`github-actions[bot]` for this marker. It updates the first match and reports duplicate matches as a
reporting infrastructure error; if no match exists, it creates one.

Required visible content:

- execution and gate status;
- commit SHA and ref;
- selected dataset names, versions, and case counts;
- aggregate scores only for trusted completed runs;
- failed case IDs and bounded reason codes;
- workflow artifact link;
- one URL per created Langfuse experiment run, and an explicit `unavailable` marker for each selected
  dataset that failed before a run was created;
- explicit infrastructure failure classification when gate is not evaluated.

Forbidden content:

- golden or provider prompts;
- generated answers or invalid drafts;
- provider request/response payloads;
- raw retrieved passages;
- credentials or environment values;
- stack traces, database errors, or raw exception strings;
- hidden reasoning.

## Non-Blocking Policy

The workflow itself visibly fails for gate or infrastructure failures, but feature 003 does not add
its check name to branch protection or required-check configuration. Reviewers use the manual
comment, artifacts, and Langfuse links as advisory evidence.

## Reporting Failure

A PR-comment failure never deletes or rewrites final evaluation JSON/Markdown or Langfuse runs. It
atomically changes only journal reporting state/failure codes, makes the final workflow exit code
`2`, and preserves the underlying evaluation status and gate result.

## Artifact Recovery

`evaluation-journal.json` is created before project preflight and included in the unconditional final
artifact upload alongside JSON and Markdown outputs. The workflow forwards `SIGINT`/`SIGTERM` to the
orchestrator and runs `recover-evaluation` with `if: always()` when final JSON or Markdown is absent
but a valid journal exists. Recovery and optional reporting finish before upload so the uploaded
journal contains terminal reporting state. Recovery failure is visible as infrastructure exit code
`2` and never causes the workflow to present an incomplete execution as evaluated.
