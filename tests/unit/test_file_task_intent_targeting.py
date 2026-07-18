# -*- coding: utf-8 -*-
from __future__ import annotations


def test_request_with_task_preserves_routing_decision() -> None:
    from app.core.agent.file_task_contract import (
        FileTaskRequest,
        FileTaskRoutingDecision,
    )
    from app.core.agent.file_task_intent_adjudication import request_with_task

    decision = FileTaskRoutingDecision(route="file_task", confidence=0.91)
    request = FileTaskRequest(task="旧任务", routing_decision=decision)

    updated = request_with_task(request, "新任务")

    assert updated.task == "新任务"
    assert updated.routing_decision is decision


def test_workflow_checkpoint_resume_preserves_routing_decision() -> None:
    from app.core.agent.file_task_contract import (
        FileTaskRequest,
        FileTaskRoutingDecision,
    )
    from app.core.agent.file_task_workflow_state import request_with_workflow_checkpoint

    decision = FileTaskRoutingDecision(route="file_task", confidence=0.91)
    request = FileTaskRequest(
        task="继续",
        routing_decision=decision,
        options={
            "workflow_checkpoint": {
                "step_index": 3,
                "target_path": "summary.docx",
            },
        },
    )

    normalized = request_with_workflow_checkpoint(request)

    assert normalized.routing_decision is decision
    assert normalized.options["workflow_checkpoint"]["step_index"] == 3
    assert normalized.target_path == "summary.docx"


def test_file_task_classification_facade_exports_routing_helpers() -> None:
    import app.core.agent.file_task_classification as classification

    assert classification.request_with_task is not None
    assert classification.trusted_file_task_routing_decision is not None
    assert classification.build_decision_context_payload is not None


def test_hybrid_plan_only_requires_confirmation_when_explicit() -> None:
    from app.core.agent.file_task_contract import (
        FileTaskClassification,
        FileTaskRequest,
    )
    from app.core.agent.file_task_intent_planner import FileTaskIntentPlanner

    planner = FileTaskIntentPlanner()
    classification = FileTaskClassification(output_mode="hybrid")

    optional = planner.plan(
        FileTaskRequest(task="分析问题并给出修改建议"), [], classification
    )
    confirmed = planner.plan(
        FileTaskRequest(task="先分析，等我确认后再应用"), [], classification
    )

    assert optional.recommended_strategy == "analyze_then_optional_apply"
    assert optional.requires_confirmation is False
    assert confirmed.recommended_strategy == "analyze_then_confirm"
    assert confirmed.requires_confirmation is True


def test_source_negation_does_not_hide_explicit_target_write_intent() -> None:
    from app.core.agent.file_task_intent_predicates import (
        has_readonly_write_negation,
        has_target_scoped_write_intent,
    )

    task = "Do not modify the source file; write the result to the current report file."

    assert has_target_scoped_write_intent(task) is True
    assert has_readonly_write_negation(task) is False


def test_keep_other_text_unchanged_does_not_cancel_explicit_save() -> None:
    from app.core.agent.file_task_intent_predicates import (
        has_readonly_write_negation,
        has_strong_write_intent,
        has_write_intent,
    )

    task = (
        "把当前 DOCX 第二段的‘需要优化的句子’替换为‘已经完成优化的句子’，"
        "只替换前文乙那一处，前文甲那一处必须保持不变，并保存文件。"
    )

    assert has_readonly_write_negation(task) is False
    assert has_strong_write_intent(task) is True
    assert has_write_intent(task) is True


def test_explicit_output_paths_join_split_directory_and_filename() -> None:
    from app.core.agent.file_task_targeting import explicit_output_paths_from_task

    paths = explicit_output_paths_from_task(
        "请基于 sales_sample.xlsx 生成文件名为 sales_profit_report.xlsx 保存到 codex_real_task_20260701 目录下",
        has_artifact_creation_intent=lambda _task: True,
    )

    assert paths == ["codex_real_task_20260701/sales_profit_report.xlsx"]


def test_explicit_output_name_does_not_include_the_instruction_prefix() -> None:
    from app.core.agent.file_task_targeting import (
        explicit_output_path_from_task,
        explicit_output_paths_from_task,
    )

    task = (
        "请阅读当前文档，生成一份名为《艺术全球规则_目录摘要.docx》的中文摘要文档，"
        "不要修改原文件。"
    )

    assert (
        explicit_output_path_from_task(
            task, has_artifact_creation_intent=lambda _task: True
        )
        == "艺术全球规则_目录摘要.docx"
    )
    assert explicit_output_paths_from_task(
        task, has_artifact_creation_intent=lambda _task: True
    ) == ["艺术全球规则_目录摘要.docx"]


def test_save_as_target_wins_over_protected_source_reference() -> None:
    from app.core.agent.file_task_intent_predicates import has_artifact_creation_intent
    from app.core.agent.file_task_targeting import (
        explicit_output_path_from_task,
        explicit_write_target_path_from_task,
    )

    task = (
        "读取工作区中的 Koto_Release_Audit_Input_20260717.docx，"
        "生成一份 5 点中文摘要，并保存为 "
        "Koto_Release_Audit_Output_20260717.docx。不要修改原文件。"
    )

    assert has_artifact_creation_intent(task) is True
    assert (
        explicit_write_target_path_from_task(task)
        == "Koto_Release_Audit_Output_20260717.docx"
    )
    assert (
        explicit_output_path_from_task(
            task, has_artifact_creation_intent=has_artifact_creation_intent
        )
        == "Koto_Release_Audit_Output_20260717.docx"
    )


def test_uncreated_request_target_is_not_read_even_when_file_flag_is_stale() -> None:
    from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
    from app.core.agent.file_task_targeting import should_skip_uncreated_target_context

    request = FileTaskRequest(
        task="生成摘要并保存为 Output.docx",
        target_path="Output.docx",
    )
    stale_output_entry = FileTaskFile(
        path="Output.docx",
        name="Output.docx",
        type="docx",
        target=False,
    )

    assert (
        should_skip_uncreated_target_context(
            request,
            stale_output_entry,
            same_path=lambda left, right: str(left).casefold() == str(right).casefold(),
            has_artifact_creation_intent=lambda _task: True,
            resolve_task_file_path=lambda _path: "",
        )
        is True
    )


def test_explicit_output_paths_exclude_second_file_in_source_list() -> None:
    from app.core.agent.file_task_targeting import explicit_output_paths_from_task

    task = (
        "综合读取 financial_analysis_source.docx 和 product_launch_brief.md，"
        "生成新的 round4_integrated_risk_register.docx，不得修改两个源文件。"
    )

    assert explicit_output_paths_from_task(
        task, has_artifact_creation_intent=lambda _task: True
    ) == ["round4_integrated_risk_register.docx"]


def test_named_new_output_is_not_reintroduced_as_a_source_file(tmp_path) -> None:
    from app.core.agent.file_task_targeting import files_explicitly_mentioned_in_task

    task = "生成一份名为《任务标识恢复验证.docx》的 DOCX 文档，写入标题。"

    assert (
        files_explicitly_mentioned_in_task(
            workspace_root=tmp_path,
            task=task,
        )
        == []
    )


def test_bare_prompt_output_name_keeps_authoritative_request_directory() -> None:
    from app.core.agent.file_task_targeting import (
        resolve_explicit_output_against_request_target,
    )

    requested = "workspace/runs/round1_financial_diagnostic.docx"

    assert (
        resolve_explicit_output_against_request_target(
            requested,
            "round1_financial_diagnostic.docx",
        )
        == requested
    )
    assert (
        resolve_explicit_output_against_request_target(requested, "other.docx")
        == "other.docx"
    )
    assert (
        resolve_explicit_output_against_request_target(
            requested,
            "workspace/explicit/round1_financial_diagnostic.docx",
        )
        == "workspace/explicit/round1_financial_diagnostic.docx"
    )
