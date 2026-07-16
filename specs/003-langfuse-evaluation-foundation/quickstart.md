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
execution/journal schemas, immutable reporting, and read-only replay.

Live validation completed on 2026-07-14 using commit `2b3096ee45489bb3396fcb30cfb1aac3592c1046`,
PR `#68`, `dataset_scope=core`, and `max_cases=1`:

- GitHub workflow run `29326562368` completed successfully with exit `0`;
- expected and resolved Langfuse project IDs matched project `Company lens`;
- the artifact bundle contained the terminal journal, immutable execution JSON, and Markdown summary;
- execution `51b307b9-0dae-4782-afec-11deb8a9e6eb` completed with `gate_status=passed`;
- Langfuse dataset `company-lens-core-golden` contained all 14 repository items, while the bounded
  experiment selected exactly one item;
- Langfuse API verification returned the selected experiment item, nine applicable item-level
  boolean scores, and 21 run-level scores including categorical `gate_status=passed`;
- the workflow published exactly one canonical marker comment to PR `#68` with matching commit,
  artifact, and Langfuse dataset-run links;
- the conditional recovery step completed without replacing the already complete execution
  artifacts; injected recovery and immutable-reporting paths remain covered by automated tests.

## 10. Inspect Langfuse

For each linked dataset run, verify:

- exact dataset version and execution metadata are visible;
- each selected item has a trace and all applicable item scores;
- completed runs have aggregate/category scores and gate status;
- partial runs show `not_evaluated` without misleading aggregate quality scores;
- no LLM-as-judge, annotation queue, or calibration output was created.

## 11. Validate Follow-up Remediation

Run focused preparation, workflow, and evaluator tests before the full repository gate:

```bash
pytest -q \
  tests/test_on_demand_preparation.py \
  tests/agent_workflow/test_preparation_resolution.py \
  tests/agent_workflow/test_prepared_followup_ticker.py \
  tests/agent_workflow/test_followup_company_sets.py \
  tests/evals/test_follow_up_checks.py
make check
```

Local focused evidence on 2026-07-16: `85 passed`.
Full local quality gate on 2026-07-16: `451 passed, 3 skipped` with Ruff and mypy green.

Expected:

- facts-only preparation performs no SEC filing, document-processing, or embedding work;
- document and hybrid requirements still prepare indexed SEC evidence;
- replace preserves the previous metric/operation while using only the new company;
- add preserves prior companies and adds the current company with mixed provenance;
- preparation enrichment does not repeat model-based company extraction.

Then run the manual workflow with `dataset_scope=follow_up`, `max_cases=100`, and PR `#68`.
Inspect the linked Langfuse run and require all four cases to pass company, metric, operation,
follow-up safety, citation, and operational-budget checks without changing gate thresholds. Run
`dataset_scope=all` only after this targeted run passes.

Targeted follow-up validation completed on 2026-07-15 using commit
`4ee1211f32009da50f02d86013e7b138bf968d0a`, PR `#68`, and `dataset_scope=follow_up`:

- GitHub workflow run `29397528843` completed successfully with execution
  `f1753314-3e06-46f1-8959-ff16c009006c` and `gate_status=passed`;
- the Langfuse dataset run `3caefcfe-174f-4c2e-a080-d0c3e1f57d59` recorded all four selected
  follow-up cases and their item-level traces and scores;
- all aggregate deterministic metrics were `1.0`, including case, company, metric, operation,
  route, required/prohibited tool, follow-up safety, citation validity, and operational budget;
- the add-company trace resolved `MDB` from the current question and retained `NET` and `DDOG`
  from follow-up context while preserving `revenue` and `quarter_over_quarter_growth`;
- facts-only preparation spans recorded `requires_financial_facts=true` and
  `requires_documents=false`, with no embedding observations;
- the canonical PR comment and immutable artifact bundle were published successfully.

## 12. Final 18-case Validation

Full live validation completed on 2026-07-15 using commit
`83d584713f0298c818656305187f99fa44d0e647`, PR `#68`, `dataset_scope=all`, and
`max_cases=100`:

- GitHub workflow run `29408339807` completed successfully with execution
  `293f117a-cb39-471e-a709-9b44c8caa362`, `status=completed`, and `gate_status=passed`;
- the core Langfuse run `1ef93ebc-6093-443e-bf43-6339f8fb70c2` linked exactly 14 unique
  dataset items to 14 unique traces;
- the follow-up Langfuse run `a0bd0cdf-c8dd-4867-a872-715b68c70694` linked exactly four unique
  dataset items to four unique traces;
- Langfuse API filtering by the shared execution ID returned exactly 18 traces, with zero
  infrastructure outcomes and zero failed citation validations;
- every aggregate quality and operational pass rate was `1.0`; `missing_result_rate` was `0.0`;
- the 2035 projection case remained `route=unsupported`, `operation=null`, and used no tools;
- the unresolved Globex follow-up retained only the current unresolved Globex identity, used no
  tools, and did not reuse any previous company;
- the terminal recovery journal contained 18 unique terminal cases and recorded PR reporting as
  `succeeded` with no reporting failure codes;
- the immutable artifact run IDs exactly matched the canonical dataset-run IDs returned by the
  Langfuse dataset-run-item API;
- local validation passed Ruff, formatting, strict mypy for 169 source files, and pytest with
  `400 passed, 3 skipped`; the CI check, web check, security scan, and image scan also passed.

Evidence links:

- GitHub workflow: <https://github.com/zvadym/company-lens/actions/runs/29408339807>
- core Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkj2qu802hnad0cak5vuplt/runs/1ef93ebc-6093-443e-bf43-6339f8fb70c2>
- follow-up Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkjjeby02zcad0cu4a6axxc/runs/a0bd0cdf-c8dd-4867-a872-715b68c70694>

## 13. Plan Reference Alias Remediation Validation

Manual run `29422586446` exposed a structured-plan variation in
`followup_replace_company_preserve_task_001`: the source branch used
`branch_id=revenue_last_five_quarters` and `dataset_ref=revenue_qoq_input`, while the calculation
used the dataset alias as its input reference. Direct branch-map indexing raised a `KeyError`, so
the execution correctly ended partial with a not-evaluated gate.

The remediation canonicalizes unique source dataset aliases to branch IDs before domain-plan
construction and converts unknown references into controlled validation errors. Validation on
commit `18c9255b697d3594de338a588cb46d611ac3f590` completed on 2026-07-15:

- targeted workflow `29445519088` passed all four follow-up cases with execution
  `f6c6f08b-aa06-422f-959c-6c780c8097e1`;
- targeted Langfuse run `56a0b560-437a-439a-9c77-22ae922a141b` contains exactly four unique item
  traces, including a passing replace-company case with DDOG, revenue, QoQ growth, calculation
  tools, and valid citations;
- full workflow `29445921451` passed all 18 cases with execution
  `136eaec8-7ff6-4205-9e08-2cc21bca7efd`;
- core Langfuse run `3195c805-73bd-463a-b9a9-726eb181c7f1` contains 14 unique item-to-trace links;
- follow-up Langfuse run `2b4f82d6-485a-4a0c-972c-3c4a464f631d` contains four unique
  item-to-trace links;
- every quality and operational pass rate is `1.0`, `missing_result_rate=0.0`, and no case has an
  infrastructure or failed-citation outcome;
- the full run recovered from two OpenAI timeouts and two OpenAI 500 responses through bounded
  per-node retries without requiring a whole-case replay;
- local validation passed Ruff, formatting, strict mypy for 170 source files, and pytest with
  `404 passed, 3 skipped`.

Evidence links:

- failing discovery run: <https://github.com/zvadym/company-lens/actions/runs/29422586446>
- targeted passing run: <https://github.com/zvadym/company-lens/actions/runs/29445519088>
- full passing run: <https://github.com/zvadym/company-lens/actions/runs/29445921451>
- targeted follow-up Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkjjeby02zcad0cu4a6axxc/runs/56a0b560-437a-439a-9c77-22ae922a141b>
- full core Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkj2qu802hnad0cak5vuplt/runs/3195c805-73bd-463a-b9a9-726eb181c7f1>
- full follow-up Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkjjeby02zcad0cu4a6axxc/runs/2b4f82d6-485a-4a0c-972c-3c4a464f631d>

## 14. Validate LLM Operation Reconciliation

Run the focused contract and workflow suites before the full repository gate:

```bash
pytest -q \
  tests/agent_workflow/test_operation_intents.py \
  tests/agent_workflow/test_operation_conflicts.py \
  tests/agent_workflow/test_operation_reconciliation.py \
  tests/agent_workflow/test_operation_reconciliation_failures.py \
  tests/agent_workflow/test_operation_reconciliation_flow.py \
  tests/agent_workflow/test_prompt_and_repair_context.py \
  tests/evals/test_agent_runner_infrastructure.py \
  tests/evals/test_operation_reconciliation_outcomes.py \
  tests/test_agent_openai_provider.py \
  tests/test_observability_security.py \
  tests/test_prompt_provider.py
make check
```

Focused reconciliation evidence on 2026-07-16 after the company-qualified metric regression fix:
`92 passed`.

Expected:

- a consistent parser/planner calculation contract makes zero
  `operation_reconciliation` model calls;
- the exact QoQ parser intent versus planner `percentage_change` regression invokes one bounded
  reconciliation sequence and produces final `quarter_over_quarter_growth` branches;
- the reconciler may update only operation, window, years, and base; topology and source requests
  remain unchanged;
- calculation `window` is accepted only for rolling averages; source periods such as "last eight
  quarters" remain in source requests;
- an add-company follow-up inherits the previous final reconciled operation;
- provider/response exhaustion produces infrastructure plus `gate_status=not_evaluated` and zero
  tools;
- a model refusal takes that infrastructure path immediately without a reconciliation retry;
- a schema-valid incompatible mapping produces observed `operation_reconciliation_failed`, a failed
  quality gate, and zero tools;
- prompt metadata, model purpose, retries, tokens, latency, and sanitized conflict/outcome metadata
  are observable without forbidden public content.

Then run the manual workflow with `dataset_scope=follow_up`, `max_cases=100`, and no PR number.
Require all four cases and every deterministic/citation/operational score to pass. Inspect Langfuse:

- consistent cases show `reconcile_operations=skipped` and no reconciliation generation;
- any conflict shows one `operation_reconciliation` generation linked under the dataset item trace;
- the final observed operation matches the reconciled plan;
- the dataset run contains exactly four unique item-to-trace links.

Only after the targeted run passes, run `dataset_scope=all`, `max_cases=100`, and PR `#68`. Require:

- execution completed with `gate_status=passed`;
- exactly 18 terminal cases and 18 Langfuse traces;
- canonical dataset-run linkage of 14 core plus four follow-up items;
- `operation_accuracy=1.0` and every other pass rate `1.0`;
- `missing_result_rate=0.0`;
- zero infrastructure outcomes and zero failed citation validations;
- successful PR reporting and immutable artifact/run ID agreement.

Append the targeted/full workflow IDs, execution IDs, Langfuse run IDs, cardinality, conflict/no-call
trace evidence, and final local test count here before changing PR `#68` from Draft.

Targeted reconciliation validation completed on 2026-07-16 using commit
`d2ae167a31cd2f0d9400999d4c93f9a00fb4776e`, workflow `29490054027`, execution
`55c1bc76-df8b-498e-b2a3-0eccfbf1298c`, and follow-up Langfuse run
`0708e8d1-767d-4c9a-9329-118750215024`:

- the execution completed with `gate_status=passed`; all four cases passed and every quality,
  citation, and operational pass rate was `1.0`, including `operation_accuracy=1.0`, while
  `missing_result_rate=0.0`;
- the canonical dataset run contained exactly four unique item-to-trace links;
- all passing reconciliation spans reported `required=false`, `attempts=0`,
  `decision_count=0`, and `outcome=not_required`, with zero `operation_reconciliation`
  generations;
- trace `75300eb1ff4de90216d788491b9192af` for the add-company case recorded two QoQ branches on the
  initial turn and three QoQ branches after adding MongoDB, proving no-call operation inheritance;
- discovery workflow `29489142585`, execution `e249d1d8-705f-4525-bb16-da8fac239267`, Langfuse
  run `527314c6-bfd8-417d-879b-4389e996c3b6`, and trace
  `1402fa5c5f840c5f26502307e8adc098` recorded one conflict generation with `required=true`,
  `conflict_reasons=[metrics]`, two decisions, one attempt, and `outcome=semantic_failure`; this
  evidence exposed company-qualified duplicate metrics and produced the typed suffix/equivalence
  regression fix validated by the passing run;
- local validation passed Ruff, formatting, strict mypy for 176 source files, and pytest with
  `454 passed, 3 skipped`; branch CI check, web check, security scan, and image scan also passed.

Evidence links:

- targeted workflow: <https://github.com/zvadym/company-lens/actions/runs/29490054027>
- passing follow-up Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkjjeby02zcad0cu4a6axxc/runs/0708e8d1-767d-4c9a-9329-118750215024>
- passing add-company trace: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/traces/75300eb1ff4de90216d788491b9192af>
- discovery conflict trace: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/traces/1402fa5c5f840c5f26502307e8adc098>

Final replay-aware validation completed on 2026-07-16. Full workflow `29490509984` first
established all 18 trace links and passed every semantic/citation check, but correctly failed the
operational gate because a permitted whole-case replay aggregated 16 model API calls against a
single-attempt ceiling of 10. Langfuse trace `9aecc506a095586c9c353b6b77fecd7f` proved the replay
through its `-retry-1` session while the public operational result could expose only the combined
`retry_count=1`. The remediation added positive privacy-safe `case_attempts`, retained the ceiling
of 10 API calls per attempt, and left aggregate latency/token/cost limits unchanged.

Targeted revalidation used commit `7b3ef90f8d88c623ee81e84f228efc17aa1e128a`, workflow
`29491463620`, execution `c1652720-da8b-4abd-96d8-fe87a4adf08c`, and follow-up Langfuse run
`432af60b-8d39-49da-ba29-6ed301495fae`. It completed 4/4 with every pass rate `1.0` and
`missing_result_rate=0.0`.

The final full validation used the same commit, workflow `29491983181`, execution
`9da79a92-4b02-4cf4-a777-6cd53643e1e0`, core Langfuse run
`619943e1-6354-4529-82ba-207ee6c8a1fb`, and follow-up Langfuse run
`99b1ac74-4aae-40ad-8715-f579997723b8`:

- the execution and both dataset runs completed with `gate_status=passed`;
- the immutable artifact and Langfuse API agreed on exactly 14 unique core traces plus four unique
  follow-up traces, with 18 unique terminal journal identities and zero failed cases;
- `operation_accuracy=1.0`, every other quality/citation/operational pass rate was `1.0`, and
  `missing_result_rate=0.0` for both datasets;
- journal reporting was `succeeded` for `zvadym/company-lens#68`, with no evaluation or reporting
  failure codes, and the canonical PR comment contained the same execution and dataset-run IDs;
- follow-up trace `2f1065b00a78f7340ad5a586d43d6b7b` demonstrated the new contract under real provider
  recovery: `case_attempts=2`, `api_calls=17`, and `retry_count=2` passed the unchanged 10-call
  per-attempt ceiling while preserving valid citations and QoQ operation inheritance;
- all passing follow-up reconciliation spans exposed sanitized `required`, intent/final operations,
  branch/decision counts, attempts, and outcome metadata; consistent plans made zero
  `operation_reconciliation` generations;
- final local validation passed Ruff, formatting, strict mypy for 176 source files, and pytest with
  `458 passed, 3 skipped`.

Final evidence links:

- targeted replay-aware workflow: <https://github.com/zvadym/company-lens/actions/runs/29491463620>
- targeted follow-up Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkjjeby02zcad0cu4a6axxc/runs/432af60b-8d39-49da-ba29-6ed301495fae>
- final full workflow: <https://github.com/zvadym/company-lens/actions/runs/29491983181>
- final core Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkj2qu802hnad0cak5vuplt/runs/619943e1-6354-4529-82ba-207ee6c8a1fb>
- final follow-up Langfuse run: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/datasets/cmrkjjeby02zcad0cu4a6axxc/runs/99b1ac74-4aae-40ad-8715-f579997723b8>
- replay-aware passing trace: <https://cloud.langfuse.com/project/cmqqaz8v303w6ad0d817ljh2t/traces/2f1065b00a78f7340ad5a586d43d6b7b>
- canonical PR comment: <https://github.com/zvadym/company-lens/pull/68#issuecomment-4968327026>
