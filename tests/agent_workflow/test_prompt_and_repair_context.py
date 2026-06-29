from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_sec_item_labels_do_not_trigger_false_abstain() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="documents",
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=(
            "Коротко по суті: у розділі **Item 1. Business / Overview** Cloudflare "
            "identified competition as a material business risk [document:cloudflare-risk].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-sec-item-label"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 0
    assert result["answer_validation"].valid is True
    assert ModelPurpose.REPAIR not in model.purposes


def test_standalone_multilingual_answer_label_completes_without_false_abstain() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="documents",
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=(
            "Коротко по суті:\n"
            "Cloudflare identified competition as a material business risk "
            "[document:cloudflare-risk].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-standalone-label"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 0
    assert result["answer_validation"].valid is True
    assert result["claims"][0].text == "Коротко по суті:"
    assert result["claims"][0].material is False
    assert ModelPurpose.REPAIR not in model.purposes


def test_answer_prompt_requires_markdown_headings_and_english_internal_artifacts() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="documents",
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=("Competition was a reported risk [document:cloudflare-risk].",),
    )

    ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-answer-prompt-contract"
    )

    answer_prompt = next(
        messages[0].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.ANSWER
    )
    parse_prompt = next(
        messages[0].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.PARSE
    )
    plan_prompt = next(
        messages[0].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.PLAN
    )
    assert "Use English for all structured fields" in parse_prompt
    assert "Use English for all structured fields" in plan_prompt
    assert "Use English for internal planning" in answer_prompt
    assert "Use Markdown headings for section labels" in answer_prompt
    assert "do not write standalone prose labels ending with ':'" in answer_prompt


def test_repair_prompt_includes_invalid_claim_previews_for_sec_label_answers() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="documents",
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=(
            "У **Item 1. Business / Overview** Cloudflare identified competition as a "
            "material business risk [invented:evidence].",
            "У **Item 1. Business / Overview** Cloudflare identified competition as a "
            "material business risk [document:cloudflare-risk].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-sec-item-label-repair"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 1
    repair_context = next(
        messages[-1].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.REPAIR
    )
    assert "invalid_claims" in repair_context
    assert "Item 1. Business / Overview" in repair_context
