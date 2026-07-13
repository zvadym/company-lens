from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass
class MutationCounters:
    project_reads: int = 0
    dataset_writes: int = 0
    item_writes: int = 0
    score_config_writes: int = 0
    score_writes: int = 0
    experiment_runs: int = 0
    flushes: int = 0


@dataclass
class FakeDatasetItem:
    id: str
    input: dict[str, Any]
    expected_output: dict[str, Any]
    metadata: dict[str, Any]
    status: str = "ACTIVE"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FakeDataset:
    id: str
    name: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    items: dict[str, FakeDatasetItem] = field(default_factory=dict)


@dataclass
class FakeScoreConfig:
    id: str
    name: str
    data_type: str
    min_value: float | None = None
    max_value: float | None = None
    categories: tuple[str, ...] = ()


@dataclass
class FakeExperimentItemResult:
    dataset_item_id: str
    trace_id: str
    output: Any
    scores: list[Any] = field(default_factory=list)


@dataclass
class FakeExperimentResult:
    dataset_run_id: str
    run_name: str
    item_results: list[FakeExperimentItemResult]
    dataset_run_url: str | None = None


class FakeProjectsApi:
    def __init__(self, owner: FakeLangfuse) -> None:
        self._owner = owner

    def get(self) -> dict[str, str]:
        self._owner.counters.project_reads += 1
        self._owner.maybe_fail("project_get")
        return {"id": self._owner.project_id, "name": self._owner.project_name}


class FakeApi:
    def __init__(self, owner: FakeLangfuse) -> None:
        self.projects = FakeProjectsApi(owner)


class FakeDatasetClient:
    def __init__(self, owner: FakeLangfuse, dataset: FakeDataset) -> None:
        self._owner = owner
        self._dataset = dataset
        self.id = dataset.id
        self.name = dataset.name
        self.items = list(dataset.items.values())

    def run_experiment(
        self,
        *,
        name: str,
        task: Callable[[FakeDatasetItem], Any],
        evaluators: Iterable[Callable[..., Any]] = (),
        **_: Any,
    ) -> FakeExperimentResult:
        self._owner.counters.experiment_runs += 1
        self._owner.maybe_fail("run_experiment")
        run_id = f"run-{self._owner.counters.experiment_runs}"
        results: list[FakeExperimentItemResult] = []
        for index, item in enumerate(self.items, start=1):
            output = task(item=item)
            scores = [evaluator(input=item.input, output=output) for evaluator in evaluators]
            results.append(
                FakeExperimentItemResult(
                    dataset_item_id=item.id,
                    trace_id=f"trace-{index}",
                    output=output,
                    scores=scores,
                )
            )
        result = FakeExperimentResult(
            run_id,
            name,
            results,
            dataset_run_url=f"https://langfuse.test/run/{run_id}",
        )
        self._owner.dataset_runs[run_id] = result
        return result


class FakeLangfuse:
    def __init__(
        self,
        *,
        project_id: str = "project-testing",
        project_name: str = "Testing",
    ) -> None:
        self.project_id = project_id
        self.project_name = project_name
        self.api = FakeApi(self)
        self.counters = MutationCounters()
        self.datasets: dict[str, FakeDataset] = {}
        self.score_configs: dict[str, FakeScoreConfig] = {}
        self.dataset_runs: dict[str, FakeExperimentResult] = {}
        self.scores: dict[str, dict[str, Any]] = {}
        self.failures: dict[str, Exception] = {}
        self._clock = datetime(2026, 1, 1, tzinfo=UTC)

    def maybe_fail(self, operation: str) -> None:
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure

    def create_dataset(
        self,
        *,
        name: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        **_: Any,
    ) -> FakeDataset:
        self.maybe_fail("create_dataset")
        self.counters.dataset_writes += 1
        dataset = self.datasets.setdefault(name, FakeDataset(id=f"dataset-{name}", name=name))
        dataset.description = description
        dataset.metadata = metadata or {}
        return dataset

    def create_dataset_item(
        self,
        *,
        id: str,
        dataset_name: str,
        input: dict[str, Any],
        expected_output: dict[str, Any],
        metadata: dict[str, Any],
        status: str = "ACTIVE",
        **_: Any,
    ) -> FakeDatasetItem:
        self.maybe_fail("create_dataset_item")
        self.counters.item_writes += 1
        self._clock += timedelta(microseconds=1)
        item = FakeDatasetItem(
            id=id,
            input=input,
            expected_output=expected_output,
            metadata=metadata,
            status=status,
            updated_at=self._clock,
        )
        self.datasets[dataset_name].items[id] = item
        return item

    def get_dataset(
        self,
        name: str,
        *,
        version: datetime | None = None,
        **_: Any,
    ) -> FakeDatasetClient:
        self.maybe_fail("get_dataset")
        dataset = self.datasets[name]
        if version is None:
            return FakeDatasetClient(self, dataset)
        pinned = FakeDataset(
            id=dataset.id,
            name=dataset.name,
            description=dataset.description,
            metadata=dict(dataset.metadata),
            items={
                item_id: item
                for item_id, item in dataset.items.items()
                if item.updated_at <= version
            },
        )
        return FakeDatasetClient(self, pinned)

    def list_score_configs(self) -> list[FakeScoreConfig]:
        self.maybe_fail("list_score_configs")
        return list(self.score_configs.values())

    def create_score_config(self, *, name: str, data_type: str, **kwargs: Any) -> FakeScoreConfig:
        self.maybe_fail("create_score_config")
        self.counters.score_config_writes += 1
        config = FakeScoreConfig(
            id=f"score-config-{name}",
            name=name,
            data_type=data_type,
            min_value=kwargs.get("min_value"),
            max_value=kwargs.get("max_value"),
            categories=tuple(
                str(category.get("label")) if isinstance(category, dict) else str(category)
                for category in (kwargs.get("categories") or ())
            ),
        )
        self.score_configs[name] = config
        return config

    def create_score(
        self,
        *,
        id: str | None = None,
        score_id: str | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        self.maybe_fail("create_score")
        self.counters.score_writes += 1
        resolved_id = score_id or id
        if resolved_id is None:
            raise ValueError("score id is required")
        score = {"id": resolved_id, **payload}
        self.scores[resolved_id] = score
        return score

    def flush(self) -> None:
        self.counters.flushes += 1
