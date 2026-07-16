# Contract: Evaluation CLI

## `sync-evaluation-datasets`

Synchronize and verify repository-authored datasets and the score contract without running the
agent.

```text
company-lens sync-evaluation-datasets
  --dataset <path> [--dataset <path> ...]
  --score-contract <path>
  [--dry-run]
  [--output <path>]
  [--pretty]
```

Defaults:

- `--dataset`: both foundation dataset paths when omitted.
- `--score-contract`: `evals/score-contracts/foundation.v1.yaml`.
- `--output`: stdout only unless supplied.

Behavior:

1. Validate all local inputs before remote writes.
2. For a real sync, resolve the key-associated project and require it to equal
   `COMPANY_LENS_LANGFUSE_PROJECT_ID` before any remote read/write. A dry-run requires the expected
   ID but performs no remote identity lookup or mutation and reports identity as not checked.
3. Create/update Langfuse datasets and active items; archive stale items.
4. Reconcile score configs.
5. Refetch exact versions and verify active IDs/counts/hashes.
6. Emit a privacy-safe JSON sync report.

Exit codes:

| Code | Meaning |
|---:|---|
| `0` | Valid dry-run or verified synchronization |
| `2` | Configuration, remote API, compatibility, or verification failure |

The command never uses provider-backed agent/model calls.

## `run-evaluation`

Run one umbrella evaluation execution.

```text
company-lens run-evaluation
  [--dataset <path> [--dataset <path> ...]]
  [--gate <path>]
  [--score-contract <path>]
  [--manifest <evaluation-execution.json>]
  --output-dir <path>
  [--max-cases <positive-int>]
  [--execution-id <uuid>]
  [--session-prefix <text>]
  [--max-concurrency <positive-int>]
  [--max-tool-calls <positive-int>]
  [--max-retries-per-node <non-negative-int>]
  [--max-repair-attempts <non-negative-int>]
  [--commit-sha <sha>]
  [--source-ref <ref>]
  [--workflow-run-url <url>]
  [--repository <owner/name>]
  [--pr-number <positive-int>]
  [--pretty]
```

Defaults:

- both foundation datasets;
- `evals/gates/eval-full.v1.yaml`;
- `evals/score-contracts/foundation.v1.yaml`;
- `artifacts/evaluations/<execution-id>/`;
- `max_concurrency=1`.

Normal mode uses the dataset/gate/score-contract defaults above. Replay mode is selected by
`--manifest`; it reads the embedded immutable manifest from a prior execution artifact.

Rules:

- `--max-cases` applies independently to each dataset.
- Every selected dataset preflights before the live agent is opened.
- `--max-concurrency` remains bounded by selected case count; the manual workflow uses `1`.
- Explicit CLI metadata overrides inferred Git/environment metadata and is recorded in the manifest.
- Normal mode requires verified `COMPANY_LENS_LANGFUSE_PROJECT_ID`, synchronizes selected datasets,
  and freezes the manifest before provider calls.
- `--repository` and `--pr-number` must be supplied together. They record the exact reporting target
  and initialize journal `reporting_status=pending`; `run-evaluation` does not call GitHub. When both
  are omitted, reporting remains `not_requested` with a null target.
- Replay mode requires a completed or partial source execution with a valid immutable manifest. It
  validates repository, gate, score-contract, model, prompt/parser/index, execution-policy, project,
  and snapshot fingerprints; opens the exact recorded remote snapshots read-only; and performs no
  dataset, item, archive, or score-config mutation.
- In replay mode, `--dataset`, `--gate`, `--score-contract`, `--max-cases`, `--max-concurrency`,
  `--max-tool-calls`, `--max-retries-per-node`, `--max-repair-attempts`, `--commit-sha`, and
  `--source-ref` are rejected. `--output-dir`, a fresh optional `--execution-id`, the paired
  `--repository`/`--pr-number` reporting target, and current workflow metadata remain allowed. The
  source execution ID and manifest fingerprint are recorded.
- The command creates `evaluation-journal.json` before remote preflight and atomically replaces it
  after each terminal transition. Final `evaluation-execution.json` and `evaluation-summary.md` are
  materialized atomically from that journal.
- `SIGINT` and `SIGTERM` checkpoint evaluation as `partial|errored/not_evaluated`, materialize partial
  artifacts, and enter `reporting/pending` when a target exists or `terminal/not_requested`
  otherwise before exiting `2`. An uncatchable stop leaves the latest valid journal for
  `recover-evaluation`.

Exit codes:

| Code | Execution status | Gate status | Meaning |
|---:|---|---|---|
| `0` | `completed` | `passed` | Trusted evaluation passed |
| `1` | `completed` | `failed` | Trusted evaluation found behavior/quality failures |
| `2` | `partial` or `errored` | `not_evaluated` | Infrastructure prevented a trustworthy quality verdict |

## `recover-evaluation`

Materialize privacy-safe partial artifacts from the last valid recovery journal without provider or
Langfuse calls.

```text
company-lens recover-evaluation
  --journal <evaluation-journal.json>
  [--output-dir <path>]
  [--pretty]
```

Rules:

- The journal must validate, have monotonic internal state, and contain at least one initialized
  execution record.
- Recovery never resumes agent work and never mutates Langfuse. It writes
  `evaluation-execution.json` and `evaluation-summary.md` with `partial|errored` and
  `gate_status=not_evaluated` unless the journal already records a trusted terminal execution.
- Recovery advances a nonterminal interrupted journal to `reporting/pending` when its stored target
  exists or `terminal/not_requested` otherwise, so the workflow can safely continue optional PR
  reporting.
- Existing valid artifacts are replaced only when their execution ID matches the journal.

Exit codes:

| Code | Meaning |
|---:|---|
| `0` | Artifacts were materialized from a valid journal |
| `2` | Journal or output validation failed |

## `report-evaluation-pr`

Create or update the canonical PR comment from existing sanitized artifacts without changing their
execution or gate result.

```text
company-lens report-evaluation-pr
  --execution <evaluation-execution.json>
  --journal <evaluation-journal.json>
  --repository <owner/name>
  --pr-number <positive-int>
  --expected-head-sha <sha>
  --artifact-url <url>
```

Rules:

- Validate both artifact schemas and require matching execution IDs. A valid journal must already
  have `phase=reporting`, `reporting_status=pending`, and a reporting target exactly matching the
  supplied repository/PR before GitHub access.
- Validate repository identity and exact PR head SHA before reading comments.
- Find the stable marker from `contracts/manual-workflow.md`; update exactly one bot-authored match,
  create one when absent, and fail on duplicates.
- Generate the body only from typed allowlisted execution fields plus the supplied artifact URL.
  Never copy arbitrary Markdown, raw errors, prompts, answers, passages, payloads, or credentials
  into the body.
- After artifact identity validation, success atomically advances the journal to
  `phase=terminal, reporting_status=succeeded`; any PR/API/permission/duplicate-marker failure
  atomically advances it to `phase=terminal, reporting_status=failed` with sanitized reporting-only
  failure codes.
- The command may change only journal sequence/time, phase, reporting status, and reporting failure
  codes. Evaluation status, gate, manifest, runs, scores, final execution JSON bytes, and Langfuse
  records remain unchanged.

Exit codes:

| Code | Meaning |
|---:|---|
| `0` | Canonical comment created or updated |
| `2` | Artifact, PR identity, permission, duplicate-marker, or API failure |

## Existing Commands

`validate-golden-dataset`, `run-golden-agent`, and `evaluate-golden-results` remain available for
focused local/unit workflows. Their implementation moves behind the eval CLI module, and gate help
text uses evaluation-gate terminology.

## Error Output

CLI errors use stable codes and bounded public messages. They may identify dataset/case/config
names, but never include credentials, raw provider exceptions, database internals, prompts, final
answers, retrieved passages, or stack traces.
