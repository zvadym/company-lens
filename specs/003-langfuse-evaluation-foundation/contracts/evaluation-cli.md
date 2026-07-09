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
2. Create/update Langfuse datasets and active items; archive stale items.
3. Reconcile score configs.
4. Refetch exact versions and verify active IDs/counts/hashes.
5. Emit a privacy-safe JSON sync report.

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
  --dataset <path> [--dataset <path> ...]
  --gate <path>
  --score-contract <path>
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
  [--pretty]
```

Defaults:

- both foundation datasets;
- `evals/gates/eval-full.v1.yaml`;
- `evals/score-contracts/foundation.v1.yaml`;
- `artifacts/evaluations/<execution-id>/`;
- `max_concurrency=1`.

Rules:

- `--max-cases` applies independently to each dataset.
- Every selected dataset preflights before the live agent is opened.
- `--max-concurrency` remains bounded by selected case count; the manual workflow uses `1`.
- Explicit CLI metadata overrides inferred Git/environment metadata and is recorded in the manifest.
- Output files are written atomically as `evaluation-execution.json` and
  `evaluation-summary.md`.

Exit codes:

| Code | Execution status | Gate status | Meaning |
|---:|---|---|---|
| `0` | `completed` | `passed` | Trusted evaluation passed |
| `1` | `completed` | `failed` | Trusted evaluation found behavior/quality failures |
| `2` | `partial` or `errored` | `not_evaluated` | Infrastructure prevented a trustworthy quality verdict |

## Existing Commands

`validate-golden-dataset`, `run-golden-agent`, and `evaluate-golden-results` remain available for
focused local/unit workflows. Their implementation moves behind the eval CLI module, and gate help
text uses evaluation-gate terminology.

## Error Output

CLI errors use stable codes and bounded public messages. They may identify dataset/case/config
names, but never include credentials, raw provider exceptions, database internals, prompts, final
answers, retrieved passages, or stack traces.
