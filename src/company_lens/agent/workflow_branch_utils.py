from __future__ import annotations
# mypy: disable-error-code="name-defined,no-any-return,misc,untyped-decorator"
# ruff: noqa: F403, F405, I001, UP037
from company_lens.agent.workflow_context import *

def _source_branch_max_attempts(state: AgentState, branch_id: str) -> int:
    plan = state["execution_plan"]
    if plan is None:
        return 1
    branches = _source_branches(plan)
    extra = state["policy"].max_tool_calls - len(branches)
    for branch in branches:
        allocated = min(state["policy"].max_retries_per_node, max(0, extra))
        if branch.branch_id == branch_id:
            return 1 + allocated
        extra -= allocated
    return 1


def _source_branches(
    plan: ExecutionPlan,
) -> tuple[DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch, ...]:
    return tuple(
        item
        for item in plan.branches
        if isinstance(item, (DocumentRetrievalBranch, FinancialFactsBranch, MacroSeriesBranch))
    )


def _on_demand_tickers(resolved: ResolvedQuery) -> tuple[str, ...]:
    tickers: list[str] = []
    for entity in resolved.entities:
        if entity.kind != "public_company":
            continue
        if entity.status == "ambiguous":
            continue
        for candidate in entity.candidates:
            ticker = candidate.canonical_value.strip().upper()
            if ticker:
                tickers.append(ticker)
    return tuple(dict.fromkeys(tickers))


def _source_request_fingerprint(
    branch: DocumentRetrievalBranch | FinancialFactsBranch | MacroSeriesBranch,
) -> str:
    payload = json.dumps(
        {
            "kind": branch.kind,
            "request": branch.request.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()

__all__ = ('_source_branch_max_attempts', '_source_branches', '_on_demand_tickers', '_source_request_fingerprint')  # noqa: E501
