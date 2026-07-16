from __future__ import annotations

from company_lens.agent.schemas import ModelExecutionBranch

_SOURCE_KINDS = {
    "retrieve_documents",
    "query_financial_facts",
    "query_macro_series",
}


def _source_dataset_aliases(
    branches: tuple[ModelExecutionBranch, ...],
    branch_ids: set[str],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for branch in branches:
        alias = branch.dataset_ref
        if branch.kind not in _SOURCE_KINDS or alias is None:
            continue
        if alias in branch_ids and alias != branch.branch_id:
            raise ValueError("Source dataset alias collides with a branch ID.")
        existing = aliases.get(alias)
        if existing is not None and existing != branch.branch_id:
            raise ValueError("Duplicate source dataset alias.")
        aliases[alias] = branch.branch_id
    return aliases


def _canonicalize_model_branch_references(
    branch: ModelExecutionBranch,
    branch_ids: set[str],
    dataset_aliases: dict[str, str],
) -> ModelExecutionBranch:
    def canonical(reference: str) -> str:
        if reference in branch_ids:
            return reference
        return dataset_aliases.get(reference, reference)

    updates: dict[str, object] = {
        "depends_on": tuple(canonical(reference) for reference in branch.depends_on)
    }
    if branch.kind == "calculate_metrics":
        updates["input_refs"] = tuple(canonical(reference) for reference in branch.input_refs)
    if branch.kind == "generate_chart_spec" and branch.dataset_ref is not None:
        updates["dataset_ref"] = canonical(branch.dataset_ref)
    return branch.model_copy(update=updates)


__all__ = (
    "_canonicalize_model_branch_references",
    "_source_dataset_aliases",
)
