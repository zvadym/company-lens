from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from company_lens.evals.manifest import ScoreConfigBinding
from company_lens.evals.score_contract import ScoreContract, ScoreDefinition


class ScoreConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconciledScoreConfigs:
    bindings: tuple[ScoreConfigBinding, ...]

    def id_for(self, score_name: str) -> str:
        for binding in self.bindings:
            if binding.score_name == score_name:
                return binding.langfuse_config_id
        raise KeyError(score_name)


def reconcile_score_configs(client: Any, contract: ScoreContract) -> ReconciledScoreConfigs:
    existing = {_value(item, "name"): item for item in _list_score_configs(client)}
    bindings: list[ScoreConfigBinding] = []
    for definition in contract.scores:
        config = existing.get(definition.name)
        if config is None:
            config = _create_score_config(client, definition)
        elif not _compatible(config, definition):
            raise ScoreConfigError(f"incompatible_score_config:{definition.name}")
        config_id = _value(config, "id")
        if not isinstance(config_id, str) or not config_id:
            raise ScoreConfigError(f"missing_score_config_id:{definition.name}")
        bindings.append(
            ScoreConfigBinding(score_name=definition.name, langfuse_config_id=config_id)
        )
    return ReconciledScoreConfigs(bindings=tuple(bindings))


def _list_score_configs(client: Any) -> list[Any]:
    direct = getattr(client, "list_score_configs", None)
    if direct is not None:
        return list(direct())
    configs: list[Any] = []
    page = 1
    while True:
        response = client.api.score_configs.get(page=page, limit=100)
        configs.extend(_value(response, "data") or ())
        meta = _value(response, "meta")
        total_pages = _value(meta, "total_pages") or _value(meta, "totalPages") or page
        if page >= int(total_pages):
            return configs
        page += 1


def _create_score_config(client: Any, definition: ScoreDefinition) -> Any:
    direct = getattr(client, "create_score_config", None)
    categories = [
        {"label": label, "value": float(index)} for index, label in enumerate(definition.categories)
    ]
    kwargs = {
        "name": definition.name,
        "data_type": definition.data_type,
        "min_value": definition.minimum,
        "max_value": definition.maximum,
        "categories": categories or None,
        "description": definition.description,
    }
    if direct is not None:
        # Test doubles accept label/value objects too, matching the public API shape.
        return direct(**kwargs)
    return client.api.score_configs.create(**kwargs)


def _compatible(config: Any, definition: ScoreDefinition) -> bool:
    data_type = str(_value(config, "data_type") or _value(config, "dataType"))
    if data_type.split(".")[-1].upper() != definition.data_type:
        return False
    if definition.data_type == "NUMERIC":
        return bool(
            _value(config, "min_value") == definition.minimum
            and _value(config, "max_value") == definition.maximum
        )
    if definition.data_type == "CATEGORICAL":
        categories = _value(config, "categories") or ()
        labels = tuple(str(_value(category, "label") or category) for category in categories)
        return labels == definition.categories
    return True


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
