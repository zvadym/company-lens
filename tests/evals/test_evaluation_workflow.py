from __future__ import annotations

from pathlib import Path

import yaml


def test_manual_workflow_matches_evaluation_contract() -> None:
    path = Path(".github/workflows/eval-full.yml")
    text = path.read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    dispatch = workflow["on"]["workflow_dispatch"]

    assert dispatch["inputs"]["dataset_scope"]["options"] == ["all", "core", "follow_up"]
    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "actions": "read",
    }
    job = workflow["jobs"]["eval-full"]
    assert job["environment"] == "Testing"
    assert "COMPANY_LENS_LANGFUSE_PROJECT_ID" in job["env"]
    assert "company-lens run-evaluation" in text
    assert "company-lens recover-evaluation" in text
    assert "company-lens report-evaluation-pr" in text
    assert "if: always()" in text
    assert "actions/upload-artifact@v4" in text
    assert "--repository" in text and "--pr-number" in text
