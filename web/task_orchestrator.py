# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import logging

_app_logger = logging.getLogger("koto.app")


class TaskOrchestrator:
    """
    编排和执行多个子任务

    责职：
    1. 顺序执行子任务
    2. 在子任务间传递数据/上下文
    3. 处理错误和重试
    4. 最终验证输出质量
    """

    @classmethod
    async def execute_compound_task(
        cls, user_input: str, subtasks: list, session_name: str = None
    ) -> dict:
        """
        执行复合任务的所有子任务

        返回:
            {
                "success": bool,
                "primary_result": 主任务结果,
                "secondary_results": [次要任务结果],
                "combined_output": 最终合并输出,
                "execution_log": 执行日志,
                "quality_score": 质量评分 (0-100),
                "errors": 错误列表
            }
        """
        execution_log = []
        results = []
        context = {"original_input": user_input, "user_input": user_input}
        errors = []

        try:
            for i, subtask in enumerate(subtasks):
                _app_logger.debug(
                    f"\n[TaskOrchestrator] 执行子任务 {i+1}/{len(subtasks)}: {subtask['task_type']}"
                )
                execution_log.append(
                    f"步骤 {i+1}: 执行 {subtask['task_type']} - {subtask['description']}"
                )
                step_input = subtask.get("input") or user_input

                try:
                    # 根据任务类型调用相应的处理函数
                    if subtask["task_type"] == "WEB_SEARCH":
                        result = await cls._execute_web_search(step_input, context)
                    elif subtask["task_type"] == "FILE_GEN":
                        result = await cls._execute_file_gen(
                            step_input, context, subtask
                        )
                    elif subtask["task_type"] == "PAINTER":
                        result = await cls._execute_painter(step_input, context)
                    elif subtask["task_type"] == "RESEARCH":
                        result = await cls._execute_research(step_input, context)
                    else:
                        result = {
                            "success": False,
                            "error": f"未知任务类型: {subtask['task_type']}",
                        }

                    subtask["status"] = "completed"
                    subtask["result"] = result
                    results.append(result)

                    # 将结果保存到上下文，供下一个任务使用
                    context[f"{subtask['task_type']}_result"] = result
                    context[f"step_{i+1}_output"] = result.get(
                        "output", result.get("content", "")
                    )

                    execution_log.append(f"  ✅ 完成: {subtask['description']}")

                except Exception as e:
                    error_msg = str(e)
                    subtask["status"] = "failed"
                    subtask["error"] = error_msg
                    errors.append(error_msg)
                    execution_log.append(f"  ❌ 失败: {error_msg}")
                    _app_logger.debug(f"[TaskOrchestrator] 子任务失败: {error_msg}")

            # 合并结果
            combined_output = cls._merge_results(subtasks, context)

            # 质量验证
            quality_score = await cls._validate_quality(
                user_input, combined_output, context
            )

            return {
                "success": len(errors) == 0,
                "primary_result": results[0] if results else None,
                "secondary_results": results[1:] if len(results) > 1 else [],
                "combined_output": combined_output,
                "execution_log": execution_log,
                "quality_score": quality_score,
                "errors": errors,
                "context": context,
            }

        except Exception as e:
            return {
                "success": False,
                "primary_result": None,
                "secondary_results": [],
                "combined_output": None,
                "execution_log": execution_log,
                "quality_score": 0,
                "errors": errors + [str(e)],
                "context": context,
            }

    @classmethod
    async def _execute_web_search(
        cls, user_input: str, context: dict, progress_callback=None
    ) -> dict:
        from web.task_orchestrator_search import execute_web_search

        return await execute_web_search(user_input, context, progress_callback)

    @classmethod
    async def _execute_ppt_multi_step(
        cls, user_input: str, context: dict, subtask: dict, progress_callback=None
    ) -> dict:
        from web.task_orchestrator_ppt import execute_ppt_multi_step

        return await execute_ppt_multi_step(
            user_input, context, subtask, progress_callback
        )

    @classmethod
    async def _execute_file_gen(
        cls, user_input: str, context: dict, subtask: dict, progress_callback=None
    ) -> dict:
        from web.task_orchestrator_filegen import execute_file_gen

        return await execute_file_gen(
            user_input,
            context,
            subtask,
            progress_callback,
            ppt_multi_step_runner=cls._execute_ppt_multi_step,
        )

    @classmethod
    async def _execute_painter(
        cls, user_input: str, context: dict, progress_callback=None
    ) -> dict:
        from web.task_orchestrator_steps import execute_painter

        return await execute_painter(user_input, context, progress_callback)

    @classmethod
    async def _execute_research(
        cls, user_input: str, context: dict, progress_callback=None
    ) -> dict:
        from web.task_orchestrator_steps import execute_research

        return await execute_research(user_input, context, progress_callback)

    @classmethod
    async def _execute_coder(
        cls, user_input: str, context: dict, progress_callback=None
    ) -> dict:
        from web.task_orchestrator_steps import execute_coder

        return await execute_coder(user_input, context, progress_callback)

    @classmethod
    async def _execute_system(
        cls, user_input: str, context: dict, progress_callback=None
    ) -> dict:
        from web.task_orchestrator_steps import execute_system

        return await execute_system(user_input, context, progress_callback)

    @classmethod
    def _merge_results(cls, subtasks: list, context: dict) -> dict:
        """合并所有子任务的结果"""
        merged = {"summary": "任务执行完成", "steps": [], "final_output": ""}

        for i, subtask in enumerate(subtasks):
            step_info = {
                "step": i + 1,
                "task": subtask["task_type"],
                "status": subtask["status"],
                "description": subtask["description"],
            }

            if subtask["result"]:
                step_info["output"] = subtask["result"].get("output", "")
            if subtask["error"]:
                step_info["error"] = subtask["error"]

            merged["steps"].append(step_info)

        # 最后一个完成的任务的输出作为最终输出
        for subtask in reversed(subtasks):
            if subtask["status"] == "completed" and subtask["result"]:
                merged["final_output"] = subtask["result"].get("output", "")
                break

        return merged

    @classmethod
    async def _validate_quality(
        cls, user_input: str, combined_output: dict, context: dict
    ) -> int:
        from web.task_orchestrator_quality import validate_quality

        return await validate_quality(user_input, combined_output, context)
