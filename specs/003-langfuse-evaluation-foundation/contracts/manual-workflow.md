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

The job uses the `Testing` environment and requires OpenAI and Langfuse credentials. FRED remains
required only when selected cases need macro data.

## Step Ordering

1. Checkout selected ref and install the project with the repository's pinned Python range.
2. Normalize secrets without printing values.
3. Preflight provider access.
4. Start PostgreSQL service, run migrations, and initialize research persistence.
5. Resolve `dataset_scope` to a fixed allowlist of repository paths.
6. Run `company-lens run-evaluation`, capture exit code without ending the job.
7. Upload the complete artifact directory with `if: always()`.
8. When `pr_number` is supplied, create/update the canonical PR comment from the sanitized Markdown
   summary and append artifact/Langfuse links.
9. Exit with the captured orchestrator code; reporting failure uses infrastructure exit code `2`.

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
- one Langfuse URL per dataset run;
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

A PR-comment failure never deletes or rewrites evaluation artifacts or Langfuse runs. It is recorded
as a reporting infrastructure failure and makes the final workflow exit code `2`, while preserving
the underlying evaluation gate result in JSON.
