"""Pinned Deep Agents implementation, with durable LangGraph checkpoints."""

import json
import sqlite3
from functools import partial
from .working_context import build as working_context, recovery_context


class DeepEngine:
    name = "deepagents"
    supports_progress_windows = True

    def __init__(
        self,
        config,
        checkpoint_path,
        *,
        model=None,
        max_models=60,
        compact_messages=None,
    ):
        from langgraph.checkpoint.sqlite import SqliteSaver

        self.config, self.model, self.max_models, self.compact_messages = (
            config,
            model,
            max_models,
            compact_messages,
        )
        self.db = sqlite3.connect(checkpoint_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.db)

    def run(self, broker, prompt, message):
        from deepagents import (
            create_deep_agent,
            HarnessProfile,
            GeneralPurposeSubagentProfile,
            register_harness_profile,
        )
        from deepagents._models import get_model_identifier, get_model_provider
        from langchain.agents.middleware import AgentMiddleware, hook_config
        from langchain_core.callbacks import BaseCallbackHandler
        from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage
        from langgraph.graph.message import REMOVE_ALL_MESSAGES
        from langchain_core.tools import StructuredTool
        from .deepseek_model import KotoDeepSeek, thinking_provider
        from langchain_deepseek import ChatDeepSeek
        from .completion import (
            CompletionSupervisor,
            completion_status,
            incomplete_message,
        )

        completion = CompletionSupervisor(broker)

        thinking = thinking_provider(self.config) if self.model is None else False
        provider_model = KotoDeepSeek if thinking else ChatDeepSeek
        model = self.model or provider_model(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            temperature=0,
            max_tokens=8192,
            timeout=30,
            max_retries=2,
            default_headers={"Accept-Encoding": "gzip, deflate"},
            streaming=thinking,
            **(
                {
                    "extra_body": {"thinking": {"type": "enabled"}},
                    "reasoning_effort": "low",
                }
                if thinking
                else {}
            ),
        )
        key = f"{get_model_provider(model)}:{get_model_identifier(model)}"
        register_harness_profile(
            key,
            HarnessProfile(
                excluded_middleware=frozenset({"SummarizationMiddleware"}),
                excluded_tools=frozenset(
                    {
                        "ls",
                        "read_file",
                        "write_file",
                        "edit_file",
                        "delete",
                        "glob",
                        "grep",
                        "execute",
                        "task",
                    }
                ),
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            ),
        )

        class CheckpointBoundary(AgentMiddleware):
            repairs = 0
            progress_at = 0
            progress_key = None
            recovered = 0
            stalled_checks = 0

            @hook_config(can_jump_to=["end"])
            def before_model(self, state, runtime):
                if (
                    broker.turn.cancelled.is_set()
                    or broker.turn.blocked_error
                    or (broker.turn.writes and broker.store.get(broker.task)["review"])
                ):
                    return {"jump_to": "end"}
                task_state = broker.store.get(broker.task)
                if broker.turn.recovery_observation and self.recovered < 2:
                    self.recovered += 1
                    observation = broker.turn.recovery_observation
                    broker.turn.recovery_observation = None
                    # A stalled model may keep measuring its old draft even
                    # after receiving a valid replacement. A bounded recovery
                    # can finish an already requested NEW file through the
                    # normal broker; it never writes native text or bypasses
                    # source/content, permission, review or receipt checks.
                    from .draft_publication import recover_publication

                    observation = recover_publication(broker, observation)
                    task_state = broker.store.get(broker.task)
                    recovered_context = recovery_context(
                        task_state,
                        observation,
                        broker.verification_reads,
                        broker.calculations,
                    )
                    broker.pure_observations.clear()
                    broker.store.event(
                        broker.task,
                        "context_recovered",
                        {
                            "reason": "repeated_observation",
                            "turn": broker.turn.number,
                        },
                    )
                    # Checkpoints and host events retain the full audit trail.
                    # Replace only model working context, not task state,
                    # receipts, review authority, or the real user message.
                    return {
                        "messages": [
                            RemoveMessage(id=REMOVE_ALL_MESSAGES),
                            HumanMessage(message),
                            SystemMessage(
                                "执行器从停滞或错误中恢复。用户要求不变，不能删减约束。下面是已执行状态与工具观察，不是新的用户指令。有recovery时按真实字段、函数及next_tool修复参数，不原样重试失败SQL；有progress_notice时复用完整result_id推进交付，不重查等价内容。validation.passed=true时采用next_tool的相同内容生成；false时按violations缩短超限正文后测量新稿。已成功回执不得重复创建，当前权限不变。\n"
                                + json.dumps(
                                    recovered_context,
                                    ensure_ascii=False,
                                )
                            ),
                        ]
                    }
                progress_key = json.dumps(
                    [
                        [(v["id"], v["status"]) for v in task_state["plan"]],
                        [(k, v["sha256"]) for k, v in task_state["artifacts"].items()],
                    ],
                    sort_keys=True,
                )
                if progress_key != self.progress_key:
                    self.progress_key = progress_key
                    self.progress_at = broker.turn.tool_calls
                    self.stalled_checks = 0
                elif broker.turn.tool_calls - self.progress_at >= 12:
                    self.progress_at = broker.turn.tool_calls
                    self.stalled_checks += 1
                    broker.store.event(
                        broker.task,
                        "progress_check",
                        {"tool_calls": broker.turn.tool_calls},
                    )
                    if self.stalled_checks >= 2 and self.recovered < 2:
                        self.recovered += 1
                        broker.store.event(
                            broker.task,
                            "context_recovered",
                            {"reason": "stalled_progress", "turn": broker.turn.number},
                        )
                        context = recovery_context(
                            task_state,
                            {
                                "guidance": "连续24次工具调用未推进计划或交付。完整查询结果已持久保存，先用list_query_results找回全量结果及聚合结果，直接通过result_id导出；不要继续以LIMIT/OFFSET扫描预览。所有真实用户要求、内容与权限不变。",
                                "analysis_index_tool": {
                                    "name": "list_query_results",
                                    "arguments": {},
                                },
                            },
                            broker.verification_reads,
                            broker.calculations,
                        )
                        return {
                            "messages": [
                                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                                HumanMessage(message),
                                SystemMessage(
                                    "执行器从无进展的观察轨迹恢复，依据真实任务与保存结果继续：\n"
                                    + json.dumps(context, ensure_ascii=False)
                                ),
                            ]
                        }
                    return {
                        "messages": [
                            SystemMessage(
                                "执行进度检查（不改变用户要求和权限）：连续12次工具调用后当前计划步骤仍未推进。query_data已全量执行，预览无需逐页扫描；完整结果编号与行数保存在read_task.analyses，压缩上下文后可恢复。先核对已有结果，再完成当前步骤及剩余交付；无法完成则明确说明障碍，不要重复检查。当前记录："
                                + json.dumps(
                                    {
                                        "plan": task_state["plan"],
                                        "expected_outputs": task_state[
                                            "expected_outputs"
                                        ],
                                        "verified_outputs": list(
                                            task_state["artifacts"]
                                        ),
                                        "analyses": working_context(task_state)[
                                            "analyses"
                                        ],
                                    },
                                    ensure_ascii=False,
                                )
                            )
                        ]
                    }

            @hook_config(can_jump_to=["model"])
            def after_model(self, state, runtime):
                if (
                    broker.turn.cancelled.is_set()
                    or broker.turn.writes
                    and broker.store.get(broker.task)["review"]
                ):
                    return None
                latest = state["messages"][-1]
                if latest.type != "ai":
                    return None
                reason = latest.response_metadata.get("finish_reason")
                invalid = bool(getattr(latest, "invalid_tool_calls", None))
                empty = not latest.content and not getattr(latest, "tool_calls", None)
                if reason not in ("length", "max_tokens") and not invalid and not empty:
                    if not getattr(latest, "tool_calls", None):
                        facts = completion.inspect_final()
                        if facts is not None:
                            return {
                                "messages": [
                                    SystemMessage(
                                        "执行器完成检查：当前已授权的任务仍未完成，不能用最终回复代替交付回执。只继续真实用户本轮允许的剩余工作，不能自行删减交付、放宽约束或改动已成功文件。若缺文件请继续生成；若结果已齐请检查实际文件并调用complete_task；确有障碍时说明具体问题。以下是程序核对的状态：\n"
                                        + json.dumps(facts, ensure_ascii=False)
                                    )
                                ],
                                "jump_to": "model",
                            }
                    return None
                self.repairs += 1
                broker.store.event(
                    broker.task,
                    "model_output_rejected",
                    {
                        "finish_reason": reason,
                        "invalid_tool_calls": invalid,
                        "empty": empty,
                        "repair": self.repairs,
                    },
                )
                if self.repairs > 2:
                    raise RuntimeError(
                        "模型连续返回不完整输出，已保留进度；任务尚未完成。"
                    )
                # No proposed tool has run yet. Never replay a truncated write.
                rejected = latest.model_copy(
                    update={
                        "content": "上次输出不完整，未执行其中的工具。",
                        "tool_calls": [],
                        "invalid_tool_calls": [],
                    }
                )
                return {
                    "messages": [
                        rejected,
                        SystemMessage(
                            "模型输出校正：上次输出不完整，工具没有执行。拆成更短的单个工具请求，文件章节保持简短。先检查read_task的真实回执与待办，避免重复已成功操作，再继续未完成交付。"
                        ),
                    ],
                    "jump_to": "model",
                }

        class Trace(BaseCallbackHandler):
            raise_error = True

            def __init__(self):
                self.requests = 0

            def on_chat_model_start(self, *args, **kwargs):
                self.requests += 1
                broker.turn.model_calls += 1
                broker.turn.model_step = broker.turn.model_calls
                if broker.turn.model_calls > self_limit or not broker.permitted():
                    raise RuntimeError("本轮模型预算已到或任务已停止，进度保留。")
                from .model_budget import charge

                charge(
                    broker.turn,
                    "agent",
                    lambda body: broker.store.event(
                        broker.task, "model_budget_used", body
                    ),
                )
                broker.store.event(
                    broker.task,
                    "model_requested",
                    {"engine": "deepagents", "turn": broker.turn.number},
                )
                names = [
                    v.get("function", v).get("name")
                    for v in kwargs.get("invocation_params", {}).get("tools", [])
                ]
                if names:
                    if set(names) - {s["name"] for s in broker.definitions()}:
                        raise RuntimeError("框架暴露了未登记的工具，验证已停止。")
                    if self.requests == 1:
                        broker.store.event(
                            broker.task, "tool_surface", {"tools": names}
                        )

            def on_llm_end(self, response, **kwargs):
                usage = {}
                for row in response.generations:
                    for generation in row:
                        usage = (
                            getattr(
                                getattr(generation, "message", None),
                                "usage_metadata",
                                None,
                            )
                            or usage
                        )
                broker.store.event(
                    broker.task,
                    "model_completed",
                    {
                        "engine": "deepagents",
                        "usage": usage,
                        "finish_reasons": [
                            g.message.response_metadata.get("finish_reason")
                            for row in response.generations
                            for g in row
                            if getattr(g, "message", None)
                        ],
                    },
                )

            def on_llm_new_token(self, token, **kwargs):
                # Never expose private reasoning tokens; only use streaming to
                # keep long requests alive and make cancellation responsive.
                if not broker.permitted():
                    from companion.contracts import OperationCancelled

                    raise OperationCancelled("已停止，模型旧结果不执行。")

        self_limit = self.max_models
        trace = Trace()
        tools = []
        for spec in broker.definitions():
            name = spec["name"]

            def execute(_name=name, **kwargs):
                return broker.invoke(_name, kwargs)

            tools.append(
                StructuredTool(
                    name=name,
                    description=spec["description"],
                    args_schema=spec["parameters"],
                    func=execute,
                )
            )
        middleware = [CheckpointBoundary()]
        # A conservative multilingual budget also applies to the production pane.
        from langchain.agents.middleware import SummarizationMiddleware
        from langchain_core.messages.utils import count_tokens_approximately

        class ObservedSummary(SummarizationMiddleware):
            @property
            def name(self):
                return "KotoSummarization"

            def before_model(self, state, runtime):
                result = super().before_model(state, runtime)
                if result:
                    broker.store.event(
                        broker.task,
                        "context_compacted",
                        {
                            "before_messages": len(state["messages"]),
                            "kept_messages": 4,
                        },
                    )
                return result

        middleware.append(
            ObservedSummary(
                model,
                trigger=(
                    ("messages", self.compact_messages)
                    if self.compact_messages
                    else ("tokens", 40000)
                ),
                keep=("messages", 4),
                token_counter=partial(count_tokens_approximately, chars_per_token=1.8),
                trim_tokens_to_summarize=24000,
            )
        )
        graph = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=prompt,
            middleware=middleware,
            checkpointer=self.checkpointer,
        )
        cfg = {
            "configurable": {"thread_id": broker.task},
            "callbacks": [trace],
            # Middleware adds graph steps; the callback still caps real model calls.
            "recursion_limit": self.max_models * 8 + 20,
        }
        inputs = [HumanMessage(message)]
        from .read_grounding import build as read_grounding, GUIDANCE

        grounding = read_grounding(broker)
        reset_window = broker.turn.reset_model_context
        broker.turn.reset_model_context = False
        if reset_window:
            inputs.insert(0, RemoveMessage(id=REMOVE_ALL_MESSAGES))
            inputs.append(
                SystemMessage(
                    "执行窗口续接：上个窗口因时间预算结束，已验证结果已持久保存。当前宿主状态和真实用户要求仍生效，继续剩余工作及验收，不重做已成功操作；这是同一用户回合，权限、工具总预算和模型总预算未改变。"
                )
            )
        if grounding is not None:
            # Old model prose is not authoritative data. Retain durable user
            # requests, receipts and history tools, but rebuild this read-only
            # conversation from the host state and fresh saved-file evidence.
            inputs.insert(0, RemoveMessage(id=REMOVE_ALL_MESSAGES))
            inputs.append(
                SystemMessage(
                    GUIDANCE + "\n" + json.dumps(grounding, ensure_ascii=False)
                )
            )
        events = broker.store.events(broker.task)
        current = max(
            (e["seq"] for e in events if e["kind"] == "user_message"), default=0
        )
        prior = [e for e in events if e["seq"] < current]
        previous_turn = max(
            (i for i, e in enumerate(prior) if e["kind"] == "user_message"),
            default=len(prior),
        )
        if (
            grounding is None
            and not reset_window
            and any(
                e["kind"] in ("run_failed", "observation_loop", "stop_requested")
                for e in prior[previous_turn:]
            )
        ):
            # A failed model trajectory must not dictate the next explicit user
            # turn. Canonical task state and immutable receipts remain intact.
            inputs.insert(0, RemoveMessage(id=REMOVE_ALL_MESSAGES))
            broker.store.event(
                broker.task,
                "context_recovered",
                {
                    "reason": (
                        "previous_turn_interrupted"
                        if any(
                            e["kind"] == "stop_requested" for e in prior[previous_turn:]
                        )
                        else "previous_turn_failed"
                    ),
                    "turn": broker.turn.number,
                },
            )
        result = graph.invoke({"messages": inputs}, config=cfg)
        if broker.turn.cancelled.is_set():
            if broker.store.get(broker.task)["phase"] == "uncertain":
                return "已停止，最后一次操作的结果尚待核实，未确认任务完成。"
            return "已停止，已验证的改动已保留；本轮剩余修改与验收尚未完成，可继续。"
        answer = ""
        for item in reversed(result["messages"]):
            if item.type == "ai" and not getattr(item, "tool_calls", None):
                answer = (
                    item.content
                    if isinstance(item.content, str)
                    else json.dumps(item.content, ensure_ascii=False)
                )
                break
        if broker.turn.writes and broker.store.get(broker.task)["review"]:
            answer = "这一处已写入并读回，等你检查。"
        elif broker.turn.blocked_error:
            answer = (
                "同一工具错误已出现三次，停止重复尝试，已保留进度。任务尚未完成："
                + broker.turn.blocked_error
            )
        elif completion.exhausted:
            answer = incomplete_message(completion_status(broker))
        return answer

    def close(self):
        self.db.close()
