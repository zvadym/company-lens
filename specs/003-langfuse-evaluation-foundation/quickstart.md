# Quickstart: Validate the Langfuse Evaluation Foundation

This guide describes the intended end-to-end validation after implementation. Contracts are in
[`contracts/`](contracts/) and the state model is in [`data-model.md`](data-model.md).

## Prerequisites

- `.env` exists and contains the required CompanyLens, OpenAI, SEC, PostgreSQL, and Langfuse values.
- `COMPANY_LENS_LANGFUSE_PROJECT_ID` identifies the intended Testing project, and the configured
  project-scoped credentials belong to that exact project.
- Docker and Python 3.12 are available.
- GitHub manual validation has a `Testing` environment with matching secrets.

Do not print or paste credentials into logs or chat.

## 1. Start the Development Stack

```bash
test -f .env
make start-dev-docker
```

Run subsequent database-backed checks against this Docker dev stack. Do not use a local SQLite file
as development truth.

## 2. Run Local Quality Checks

```bash
python -m pip install -e ".[dev]"
make check
```

Expected: Ruff, strict mypy, and pytest all pass.

## 3. Validate Golden Coverage

```bash
company-lens validate-golden-dataset \
  --dataset evals/datasets/golden/core.v1.yaml \
  --pretty

company-lens validate-golden-dataset \
  --dataset evals/datasets/golden/follow_up.v1.yaml \
  --pretty
```

Expected across both summaries:

- 18-25 total cases;
- at least two cases in every defined category;
- citation modes resolve to `required` or `not_applicable`;
- valid, missing-attempt, unknown-evidence-attempt, and semantic-mismatch-attempt coverage exists.

## 4. Preview Langfuse Synchronization

```bash
company-lens sync-evaluation-datasets \
  --dataset evals/datasets/golden/core.v1.yaml \
  --dataset evals/datasets/golden/follow_up.v1.yaml \
  --score-contract evals/score-contracts/foundation.v1.yaml \
  --dry-run \
  --pretty
```

Expected: planned active upserts, stale archives, score-config reconciliation, deterministic item
IDs, and local hashes are shown without remote writes or provider calls.

## 5. Synchronize and Verify Exact Snapshots

```bash
company-lens sync-evaluation-datasets \
  --dataset evals/datasets/golden/core.v1.yaml \
  --dataset evals/datasets/golden/follow_up.v1.yaml \
  --score-contract evals/score-contracts/foundation.v1.yaml \
  --output artifacts/evaluations/sync-report.json \
  --pretty
```

Expected:

- the public project lookup returns the configured expected project ID before any dataset write;
- one Langfuse dataset per repository dataset;
- every repository case appears once with matching content hash;
- stale items are archived;
- exact version timestamps are returned;
- all score definitions resolve to compatible Langfuse score-config IDs.

Run the command a second time. Expected: no duplicates and the same deterministic item IDs.

## 6. Run a Small Live Evaluation

```bash
company-lens run-evaluation \
  --dataset evals/datasets/golden/core.v1.yaml \
  --gate evals/gates/eval-full.v1.yaml \
  --score-contract evals/score-contracts/foundation.v1.yaml \
  --output-dir artifacts/evaluations/manual-smoke \
  --max-cases 2 \
  --max-concurrency 1 \
  --pretty
```

Expected:

- synchronization verification finishes before the first provider-backed case;
- one isolated PostgreSQL research session is used per case;
- Langfuse shows one dataset run with item traces and applicable deterministic scores;
- `evaluation-execution.json` validates against
  `contracts/evaluation-execution.schema.json`;
- `evaluation-journal.json` validates against `contracts/evaluation-journal.schema.json` and reaches
  a terminal sequence;
- `evaluation-summary.md` contains no raw answer, prompt, evidence passage, provider payload,
  exception text, credential, or stack trace;
- exit code is `0`, `1`, or `2` according to the CLI contract.

## 7. Replay the Recorded Manifest

Use the execution artifact from the small live evaluation:

```bash
company-lens run-evaluation \
  --manifest artifacts/evaluations/manual-smoke/evaluation-execution.json \
  --output-dir artifacts/evaluations/manual-smoke-replay \
  --pretty
```

Expected:

- the replay creates a new execution ID with `replay_of_execution_id` and the source manifest
  fingerprint;
- local dataset, gate, score-contract, model, prompt/parser/index, policy, project, and snapshot
  fingerprints match the source manifest;
- the exact recorded Langfuse snapshots are fetched read-only;
- no dataset/item/archive/score-config mutation occurs;
- a mismatch or unavailable snapshot causes zero provider calls and exit `2`.

## 8. Validate Failure and Recovery Semantics

Use focused tests rather than intentionally damaging shared remote data:

```bash
pytest -q \
  tests/evals/test_langfuse_sync.py \
  tests/evals/test_langfuse_experiment.py \
  tests/evals/test_evaluation_orchestrator.py \
  tests/evals/test_evaluation_reporting.py \
  tests/evals/test_run_evaluation_cli.py
```

The tests must prove:

- remote hash mismatch causes zero provider calls and exit `2`;
- wrong expected project ID causes zero remote writes, zero provider calls, and exit `2`;
- with a PR target, wrong-project or snapshot preflight failure still reaches `reporting/pending` and
  can publish a sanitized not-evaluated PR summary; without a target it reaches
  `terminal/not_requested`;
- captured missing answer is a behavior failure and can produce exit `1`;
- provider/evaluator failure yields partial/errored plus `gate_status=not_evaluated` and exit `2`;
- incomplete SDK item results never produce aggregate quality scores;
- not-applicable citation cases emit no citation score and do not enter the denominator;
- every injected terminal-transition interruption leaves a valid, monotonic, privacy-safe journal;
- `SIGINT`/`SIGTERM` materializes partial artifacts, and `recover-evaluation` reconstructs them from
  the last valid journal without provider or Langfuse calls.

Example recovery command:

```bash
company-lens recover-evaluation \
  --journal artifacts/evaluations/interrupted/evaluation-journal.json \
  --output-dir artifacts/evaluations/interrupted \
  --pretty
```

## 9. Run the Manual GitHub Workflow

In GitHub Actions, open the evaluation workflow, select **Run workflow**, choose the branch/ref and
`dataset_scope`, optionally supply a PR number, and run it.

Expected:

- one Langfuse dataset run per selected repository dataset;
- all runs share one execution ID and manifest fingerprint;
- one artifact bundle is uploaded even when evaluation fails;
- the bundle includes the journal and recovered partial JSON/Markdown when interruption occurred;
- when a PR number is supplied, exactly one canonical comment is created or updated;
- the journal target exactly matches the repository/PR and reporting finishes `succeeded|failed`;
- infrastructure/preflight failure comments show `not_evaluated` without requiring verified remote
  snapshots or exposing raw errors, and show Langfuse run output as `unavailable` when no experiment
  run was created;
- an injected reporting failure leaves evaluation status, gate, manifest, runs, scores, final JSON,
  and Langfuse records unchanged while the workflow exits `2`;
- the final workflow result reflects the orchestrator exit code but is not configured as a required
  branch-protection check by this feature.

This final check is environment-only: it requires the repository's `Testing` environment, live
project-scoped Langfuse/OpenAI credentials, and a real PR head ref. Local implementation validation
covers the workflow contract, fake-backed project mismatch/sync/experiment/reporting paths, exact
execution/journal schemas, immutable reporting, and read-only replay; it does not claim that a live
Testing workflow was executed from a developer machine.

## 10. Inspect Langfuse

For each linked dataset run, verify:

- exact dataset version and execution metadata are visible;
- each selected item has a trace and all applicable item scores;
- completed runs have aggregate/category scores and gate status;
- partial runs show `not_evaluated` without misleading aggregate quality scores;
- no LLM-as-judge, annotation queue, or calibration output was created.
