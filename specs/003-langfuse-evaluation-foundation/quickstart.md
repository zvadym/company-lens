# Quickstart: Validate the Langfuse Evaluation Foundation

This guide describes the intended end-to-end validation after implementation. Contracts are in
[`contracts/`](contracts/) and the state model is in [`data-model.md`](data-model.md).

## Prerequisites

- `.env` exists and contains the required CompanyLens, OpenAI, SEC, PostgreSQL, and Langfuse values.
- Langfuse credentials target the intended Testing project.
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
- `evaluation-summary.md` contains no raw answer, prompt, evidence passage, provider payload,
  exception text, credential, or stack trace;
- exit code is `0`, `1`, or `2` according to the CLI contract.

## 7. Validate Failure Semantics

Use focused tests rather than intentionally damaging shared remote data:

```bash
pytest -q \
  tests/test_langfuse_eval_sync.py \
  tests/test_langfuse_experiment.py \
  tests/test_evaluation_orchestrator.py \
  tests/test_evaluation_reporting.py
```

The tests must prove:

- remote hash mismatch causes zero provider calls and exit `2`;
- captured missing answer is a behavior failure and can produce exit `1`;
- provider/evaluator failure yields partial/errored plus `gate_status=not_evaluated` and exit `2`;
- incomplete SDK item results never produce aggregate quality scores;
- not-applicable citation cases emit no citation score and do not enter the denominator;
- partial artifacts survive and remain privacy-safe.

## 8. Run the Manual GitHub Workflow

In GitHub Actions, open the evaluation workflow, select **Run workflow**, choose the branch/ref and
`dataset_scope`, optionally supply a PR number, and run it.

Expected:

- one Langfuse dataset run per selected repository dataset;
- all runs share one execution ID and manifest fingerprint;
- one artifact bundle is uploaded even when evaluation fails;
- when a PR number is supplied, exactly one canonical comment is created or updated;
- the final workflow result reflects the orchestrator exit code but is not configured as a required
  branch-protection check by this feature.

## 9. Inspect Langfuse

For each linked dataset run, verify:

- exact dataset version and execution metadata are visible;
- each selected item has a trace and all applicable item scores;
- completed runs have aggregate/category scores and gate status;
- partial runs show `not_evaluated` without misleading aggregate quality scores;
- no LLM-as-judge, annotation queue, or calibration output was created.
