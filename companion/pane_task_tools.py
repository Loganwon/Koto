"""Native Office boundaries around the shared, checkpointed Agent runtime."""

import uuid

from .tool_contracts import tool
from .contracts import (
    CompanionError,
    DocumentConflict,
    OperationCancelled,
    ResultUncertain,
)
from .reading import DeferredSnapshot
from .agent_lab.documents import BoundTextDocument
from .agent_lab.tools import ToolBroker, WorkspaceSources
from .agent_lab.data_engine import DataEngine
from .agent_lab.store import TaskStore
from .agent_lab.deep_engine import DeepEngine


class PaneTaskStore(TaskStore):
    revision = 0
    dependencies = ()

    def checkpoint(self, task, receipt):
        receipt["plan_revision"] = self.revision
        receipt["declared_sources"] = list(self.dependencies)
        return super().checkpoint(task, receipt)

    def receipt(self, task, receipt, **kwargs):
        receipt["plan_revision"] = self.revision
        receipt["declared_sources"] = list(self.dependencies)
        return super().receipt(task, receipt, **kwargs)


class NativeDocument(BoundTextDocument):
    def __init__(self, port, target, journal, scope, task):
        super().__init__(port, target)
        self.expected = {f.id: f.text for f in target.fragments}
        self.journal, self.scope, self.task = journal, scope, task

    def verify(self):
        for fragment, expected in self.expected.items():
            if self.read(fragment) != expected:
                raise DocumentConflict(
                    "选区内容已经由用户改变，请重新选择并预判；没有覆盖人工修改。"
                )

    def replace(self, fragment, expected, replacement, permitted):
        with self.journal.document_lock(self.scope):
            return self._replace_checked(fragment, expected, replacement, permitted)

    def _replace_checked(self, fragment, expected, replacement, permitted):
        if expected != self.expected.get(fragment):
            raise DocumentConflict("建议使用的原文版本已经过期；没有覆盖人工修改。")
        action = uuid.uuid4().hex
        self.journal.record(
            self.scope,
            self.task,
            action,
            "write_requested",
            {"fragment": fragment, "before": expected},
            action,
        )
        try:
            actual = super().replace(fragment, expected, replacement, permitted)
        except ResultUncertain:
            raise
        except (DocumentConflict, OperationCancelled):
            self.journal.record(
                self.scope, self.task, action, "write_rejected", {}, action
            )
            raise
        except Exception as error:
            raise ResultUncertain("宿主操作结果待核实，不自动重做。") from error
        self.expected[fragment] = actual
        self.journal.record(
            self.scope,
            self.task,
            action,
            "write_verified",
            {"fragment": fragment, "before": expected, "after": actual},
            action,
        )
        return actual

    def full_snapshot(self):
        return self.port.text_snapshot(self.target.id)


class NativeBroker(ToolBroker):
    def __init__(
        self, store, task, workspace, outputs, document, verifier, edit_allowed
    ):
        root = workspace.tree()["root"]
        super().__init__(store, task, root, outputs, document, verifier)
        # Reuse the user's workspace registry, including excluded credentials,
        # path confinement, generation and live unsaved-document reader.
        self.workspace = workspace
        self.live_reader = document.port.read_open_file
        self.data = DataEngine(
            workspace, self.outputs.parent / "analysis", self.permitted
        )
        self.edit_allowed, self.allowed_fragments = edit_allowed, set()
        self.interaction = "start"
        spec = tool(
            "preserve_fragment",
            "Explicitly keep an allowed native fragment unchanged, after reading and comparing it. Records coverage without a host write. Use when the user wants part of the selection preserved; then continue to other fragments. Never apply_edit identical text just to mark progress.",
            {
                "fragment_id": {"type": "string"},
                "expected": {"type": "string"},
                "reason": {"type": "string"},
            },
            ["fragment_id", "expected", "reason"],
        )
        self.specs["preserve_fragment"] = {**spec["function"], "effect": "progress"}
        for name, description, properties in [
            (
                "read_current_document",
                "Read full native document text and tables by page. Follow next; do not claim unprovided regions were read.",
                {
                    "start": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 12000},
                },
            ),
            (
                "search_current_document",
                "Search the full native document, including table text.",
                {"query": {"type": "string"}},
            ),
        ]:
            spec = tool(
                name,
                description,
                properties,
                ["query"] if "query" in properties else [],
            )
            self.specs[name] = {**spec["function"], "effect": "read"}
        for spec in self.specs.values():
            if spec["effect"] == "write":
                spec["parameters"]["properties"]["source_ids"] = {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string"},
                }
                spec[
                    "description"
                ] += " source_ids lists only actual reference inputs read for THIS operation; omit unrelated reads."
        from .native_content_checks import install

        install(self)

    def bind_turn(self, turn):
        previous = self.references
        reads = getattr(self, "verification_reads", [])
        analyses = getattr(self, "analysis_evidence", [])
        super().bind_turn(turn)
        self.references = WorkspaceSources(
            self.workspace, self.workspace.tree()["generation"], self.live_reader
        )
        self.full_document = DeferredSnapshot(
            self.document.target.name, self.document.full_snapshot
        )
        from .native_read_context import restore

        restore(self, previous, reads, analyses)

    def definitions(self):
        pending_native = self.edit_allowed and (
            set(self.document.fragments) - self.processed_fragments()
        )
        return [
            s
            for s in super().definitions()
            if not pending_native
            or not (
                s["name"].startswith("create_")
                or s["name"] in {"copy_reference", "copy_artifact", "rename_artifact"}
            )
            if s["name"] != "apply_edit" or self.edit_allowed and self.allowed_fragments
            if s["name"] != "preserve_fragment"
            or self.edit_allowed
            and self.allowed_fragments
            and self.turn.mode != "read"
            and self.interaction in ("start", "continue")
        ]

    def processed_fragments(self):
        state = self.store.get(self.task)
        return {
            e["fragment"]
            for e in state["edits"]
            if e.get("plan_revision") == self.store.revision
        } | {
            key
            for key, value in state.get("native_retained", {}).items()
            if value["plan_revision"] == self.store.revision
        }

    def invoke(self, name, args):
        if isinstance(args, dict) and isinstance(args.get("action_id"), str):
            args = {
                **args,
                "action_id": "plan-"
                + str(self.store.revision)
                + ":"
                + args["action_id"],
            }
        return super().invoke(name, args)

    def action_payload(self, name, args):
        # Provenance metadata is consumed by _run, not an operation argument.
        return super().action_payload(
            name, {k: v for k, v in args.items() if k != "source_ids"}
        )

    def validate_write(self, name, args):
        from .native_content_checks import check
        from .native_sources import verified_sources

        check(self, name, args)
        # Reject absent provenance before spending a model verification call.
        verified_sources(self, args.get("source_ids", []))

    def write_context(self):
        # These are host-owned, read-back-verified current texts, including the
        # latest feedback. Old model summaries are not a substitute for them.
        return {"native_fragments": dict(self.document.expected)}

    def _run(self, name, args):
        if name == "set_native_content_checks":
            from .native_content_checks import declare

            return declare(self, args)
        if name == "preserve_fragment":
            state = self.store.get(self.task)
            if (
                not self.edit_allowed
                or self.turn.mode == "read"
                or self.interaction not in ("start", "continue")
                or state["review"]
                or args["fragment_id"] not in self.allowed_fragments
            ):
                raise CompanionError("本轮不能确认保留这个片段。")
            self.document.verify()
            if self.document.read(args["fragment_id"]) != args["expected"]:
                raise DocumentConflict("待保留片段已变化，请重新核对。")
            receipt = {**args, "plan_revision": self.store.revision}
            self.store.change(
                self.task,
                native_retained={
                    **state.get("native_retained", {}),
                    args["fragment_id"]: receipt,
                },
            )
            self.store.event(self.task, "fragment_preserved", receipt)
            return {"preserved": receipt, "native_write": False}
        if name == "read_current_document":
            return self.full_document.read(**args)
        if name == "search_current_document":
            return self.full_document.search(**args)
        if name == "apply_edit":
            if (
                not self.edit_allowed
                or args["fragment_id"] not in self.allowed_fragments
            ):
                raise CompanionError(
                    "这个片段不属于本次明确操作；继续只处理未完成片段，反馈只调整当前检查点。"
                )
            if args["expected"] == args["text"]:
                raise CompanionError(
                    "原文没有变化，请用preserve_fragment确认保留，不重复写入相同文字。"
                )
        if name.startswith("create_"):
            if (
                args.get("file_name")
                not in self.store.get(self.task)["expected_outputs"]
            ):
                raise CompanionError("文件不在当前已接受的交付清单中；请核对交付清单。")
            if self.edit_allowed:
                covered = self.processed_fragments()
                if set(self.document.fragments) - covered:
                    raise CompanionError(
                        "先逐段完成并检查原文，再生成交付文件，以采用最新反馈。"
                    )
        if name == "complete_task" and self.edit_allowed:
            covered = self.processed_fragments()
            if set(self.document.fragments) - covered:
                raise CompanionError("当前选区还有未处理片段，任务尚未完成。")
            self.document.verify()
        if self.specs.get(name, {}).get("effect") == "write":
            args = dict(args)
            declared = args.pop("source_ids", [])
            if name == "apply_edit":
                contract = (
                    self.store.get(self.task)
                    .get("native_content_checks", {})
                    .get(args["fragment_id"], {})
                )
                if contract.get("plan_revision") == self.store.revision:
                    declared = list(
                        dict.fromkeys(
                            [
                                *declared,
                                *(
                                    s["file_id"]
                                    for fact in contract.get("facts", [])
                                    for s in fact["sources"]
                                ),
                            ]
                        )
                    )
            from .native_sources import verified_sources

            self.store.dependencies = verified_sources(self, declared)
        return super()._run(name, args)


class NativeDeepEngine(DeepEngine):
    def run(self, broker, prompt, message):
        import json

        context = {
            "interaction": broker.interaction,
            "selected_reference_ids": broker.selected_sources,
            "allowed_fragment_ids": sorted(broker.allowed_fragments),
            "bound_name": broker.document.target.name,
        }
        from .native_read_context import context as read_context

        context.update(read_context(broker))
        prompt += """
你现在运行在真实Office/WPS任务窗格，read_document返回绑定范围；全文、表格可按需用read_current_document/search_current_document。
本次ui_context是宿主明确操作，不是对用户文本的意图分类。feedback只调整允许的当前片段；continue保留已检查结果并推进允许的未完成片段。
同一用户目标的原文修改和所有交付文件必须连续完成。当前片段完成后立即停止等检查；全部片段检查后继续生成所有文件。
开始前先读取绑定范围和实际引用资料，按真实工具结果更新计划。不要只做第一个文件就回答完成。
verified_reference_reads与verified_analyses是宿主重新核对版本后续接的真实已读片段/查询结果，本轮可以直接复用，不必为了source_ids重复读取。invalidated_source_ids中的旧资料已失效，必须重新读取或查询，不能使用旧历史事实。没有列出的内容不能声称已读。
当前工具清单按原文检查点阶段收窄：未检查完原文前不开放文件创建，检查完再继续即可获得交付工具，无需重新预判。
read_task中当前expected_outputs与plan_revision优先于旧工具消息；旧版输出不是本版交付的完成证据。
只有图中声明的交付能创建。source_ids填写本次操作实际使用的来源ID，不能把读过的所有文件都声明为引用。
原文使用query_data数字前，必须set_native_content_checks绑定当前fragment_id及真实query_facts单元格、原始单位和输出单位；使用返回required_phrases原样写入正文。money_product_cents返回整数分，5400分=54.00元，不能把分当元。模型保存的constraints不是事实证据。
"""
        prompt += "\nui_context:\n" + json.dumps(context, ensure_ascii=False)
        return super().run(broker, prompt, message)
