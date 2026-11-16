"""Real task-pane lifecycle: read-only preparation, accepted plan, native checkpoints."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

from .contracts import (
    CompanionError,
    DocumentConflict,
    ResultUncertain,
    OperationCancelled,
)
from .journal import document_scope
from .pane_activity import public_activity
from .workspace import LocalWorkspace
from .file_actions import FileActions
from .agent_lab.preflight import (
    DeliveryPreflight,
    snapshot,
    fingerprint,
    validate_estimate,
)
from .agent_lab.runtime import LabSession, WriteVerifier
from .agent_lab.task_requirements import TaskRequirements
from .pane_task_tools import (
    PaneTaskStore,
    NativeDocument,
    NativeBroker,
    NativeDeepEngine,
)


class PaneTaskSession:
    def __init__(
        self,
        documents,
        workspace,
        config_factory,
        journal,
        *,
        state_dir=None,
        engine_factory=None,
        predictor_factory=None,
        requirements_factory=None,
    ):
        self.documents, self.workspace = documents, workspace
        self.config_factory, self.journal = config_factory, journal
        base = (
            Path(state_dir)
            if state_dir
            else Path(os.environ.get("LOCALAPPDATA", Path.home()))
            / "Koto"
            / "Addin"
            / "agent"
        )
        self.folder = base / uuid.uuid4().hex
        self.folder.mkdir(parents=True, exist_ok=True)
        self.store = PaneTaskStore(self.folder / "tasks.sqlite3")
        self.engine_factory = engine_factory or (
            lambda config, path: NativeDeepEngine(config, path)
        )
        self.predictor_factory = predictor_factory or DeliveryPreflight
        self.requirements_factory = requirements_factory or TaskRequirements
        self.lock = threading.RLock()
        self.busy, self.closed = False, False
        self.phase, self.message, self.revision = "idle", "", 0
        self.cancelled = threading.Event()
        self.lab = self.engine = self.document = self.target = self.prepared = None
        self.task, self.scope, self.instruction, self.turn = None, None, "", ""
        self.answer, self.error, self.history = "", "", []
        self.recovery = None
        self.resources, self.source_ids, self._past_requests = [], [], []
        self.readers, self.config_at_plan = None, None
        self.plan_revision, self._event_cursor, self.sources_read = 0, 0, {}
        self.activity = []
        self.generation = None
        self.outputs = None
        self._engine_config = None
        self._format_choices = []
        self._plan_context = None

    def restore_history(self, observation):
        scope = document_scope(observation.get("host", ""), observation.get("path"))
        if self.target or self.busy or not scope or scope == self.scope:
            return
        self.scope = scope
        recovered = self.journal.recovery(scope)
        self.history = recovered.pop("history")
        self.recovery = recovered if self.history or recovered["unverified"] else None

    def history_page(self, before=None, query="", limit=20):
        return self.journal.history_page(self.scope or "unbound", before, query, limit)

    def _set(self, phase, message=""):
        with self.lock:
            self.phase, self.message = phase, message
            self.revision += 1

    def _launch(self, action, phase):
        with self.lock:
            if self.busy or self.closed:
                raise CompanionError("当前操作尚未结束，请先停止或等待。")
            self.cancelled = threading.Event()
            self.busy, self.error = True, ""
            self._set(phase)

        def work():
            try:
                action()
            except Exception as error:
                with self.lock:
                    self.error = (
                        str(error)
                        if isinstance(error, CompanionError)
                        else "这一步未完成，输入与已完成结果已保留。"
                    )
                    if isinstance(error, ResultUncertain):
                        self._set("uncertain", self.error)
                    elif isinstance(error, DocumentConflict):
                        self._set("conflict", self.error)
                    elif self.cancelled.is_set():
                        self._set("stopped", "已停止，已完成内容保留。")
                    else:
                        self._set("error", self.error)
            finally:
                with self.lock:
                    if self.phase == "stopping":
                        self._set("stopped", "已停止，已完成内容保留。")
                    self.busy = False
                if self.closed and self.engine:
                    self.engine.close()
                if self.closed:
                    self.store.close()

        threading.Thread(target=work, daemon=True, name="KotoPaneTask").start()
        return self.snapshot()

    def prepare(self, instruction, file_ids=(), previous_plan_id=None):
        if (
            not isinstance(instruction, str)
            or not instruction.strip()
            or len(instruction) > 6000
        ):
            raise CompanionError("请输入不超过6000字的任务要求。")
        if (
            not isinstance(file_ids, (list, tuple))
            or len(file_ids) > 8
            or any(not isinstance(v, str) for v in file_ids)
        ):
            raise CompanionError("一次最多加入8份工作区资料。")
        file_ids = list(dict.fromkeys(file_ids))
        config = self.config_factory()
        previous = self.prepared
        reuse = bool(
            previous
            and previous_plan_id == previous["id"]
            and self.task
            and self.target
        )
        past = (
            [*self._past_requests, self.instruction][-6:]
            if reuse and instruction.strip() != self.instruction
            else list(self._past_requests) if reuse else []
        )
        if any(len(v) > 6000 for v in past):
            raise CompanionError("先前任务要求过长，请开启新任务。")

        def plan():
            if reuse:
                if self.store.get(self.task)["phase"] == "uncertain":
                    raise ResultUncertain(
                        "上次操作待核实；重新选择范围并开启新任务，不重放旧操作。"
                    )
                self.document.verify()
                target = self.target
            else:
                target = self.documents.bind_current()
                with self.lock:
                    self.task = self.store.create(instruction.strip())
                    self.scope = (
                        document_scope(target.host, target.path)
                        or "unbound:" + self.task
                    )
                    self.document = NativeDocument(
                        self.documents, target, self.journal, self.scope, self.task
                    )
                    self.target = target
                    self.plan_revision, self._event_cursor, self.sources_read = 0, 0, {}
                    self.activity = []
                    recovered = self.journal.recovery(self.scope)
                    self.history = recovered.pop("history")
                    self.recovery = (
                        recovered if self.history or recovered["unverified"] else None
                    )
            self.source_ids = file_ids
            self._past_requests = past
            self.instruction = instruction.strip()
            self.turn = self.instruction
            self.answer = ""
            self.prepared = None
            self._format_choices = []
            self.readers = self.workspace.session(self.documents.read_open_file)
            resources = []
            for file_id in file_ids:
                value = self.readers.read(file_id, 0, 1500)
                resources.append(
                    {
                        "id": "file:"
                        + hashlib.sha256(file_id.encode()).hexdigest()[:20],
                        "file_id": file_id,
                        "name": self.workspace._path(file_id).name,
                        "revision": value["version"],
                        "excerpt": value["text"],
                    }
                )
            current = self.document.contents()
            native_version = fingerprint(current)
            resources.append(
                {
                    "id": "selection",
                    "name": target.name,
                    "file_id": None,
                    "revision": native_version,
                    "excerpt": (target.scope + "\n" + "\n".join(current.values()))[
                        :1500
                    ],
                }
            )
            self.resources = resources
            capabilities = {
                "revision": "native-pane-v1",
                "create_formats": ["docx", "xlsx", "pptx"],
                "edit_bound_target": all(
                    f.editable and f.kind == "text" for f in target.fragments
                ),
            }
            context = snapshot(
                self.instruction,
                resources,
                {
                    "id": target.id,
                    "name": target.name,
                    "revision": native_version,
                    "scope": target.scope,
                    "fragment_ids": list(current),
                },
                capabilities,
                previous_requests=past,
            )
            estimate = self.predictor_factory(config).predict(
                context, cancelled=self.cancelled
            )
            if estimate["can_prepare"]:
                estimate["task_contract"] = self.requirements_factory(config).compile(
                    context, estimate, cancelled=self.cancelled
                )
                accepted = {
                    (d["kind"], d["name"])
                    for d in estimate["task_contract"]["deliverables"]
                }
                removed = [
                    d
                    for d in estimate["deliveries"]
                    if (d["kind"], d["name"]) not in accepted
                ]
                if removed:
                    # The estimate is a proposal. The independently compiled
                    # human contract owns scope, especially native write intent.
                    estimate["deliveries"] = [
                        d
                        for d in estimate["deliveries"]
                        if (d["kind"], d["name"]) in accepted
                    ]
                    estimate["summary"] = (
                        "按已核对要求生成："
                        + "、".join(d["name"] for d in estimate["deliveries"])
                        + "。"
                        if estimate["deliveries"]
                        else "仅回答问题，不修改原文或生成文件。"
                    )
                    self.store.event(
                        self.task,
                        "delivery_estimate_scope_corrected",
                        {
                            "removed": [
                                {"kind": d["kind"], "name": d["name"]} for d in removed
                            ]
                        },
                    )
            if self.cancelled.is_set():
                self._set("stopped", "已停止预判，未修改文件。")
                return
            self.config_at_plan = config
            self._plan_context = context
            self.generation = self.workspace.tree()["generation"]
            self.prepared = {"id": uuid.uuid4().hex, **estimate}
            self.store.event(self.task, "delivery_estimate", self.prepared)
            self._set("planned", estimate["summary"])

        return self._launch(plan, "planning")

    def adjust_plan(self, plan_id, file_name, new_format):
        with self.lock:
            if (
                self.busy
                or self.phase != "planned"
                or not self.prepared
                or self.prepared["id"] != plan_id
            ):
                raise CompanionError("请在执行前调整当前交付计划。")
            if new_format not in ("docx", "xlsx", "pptx", "pdf"):
                raise CompanionError("这个交付格式尚未支持。")
            raw = {k: self.prepared[k] for k in ("summary", "questions", "warnings")}
            raw["deliveries"] = [
                {
                    k: d[k]
                    for k in (
                        "kind",
                        "name",
                        "format",
                        "target_id",
                        "source_ids",
                        "reason",
                    )
                }
                for d in self.prepared["deliveries"]
            ]
            chosen = next(
                (
                    d
                    for d in raw["deliveries"]
                    if d["kind"] == "create" and d["name"] == file_name
                ),
                None,
            )
            if not chosen:
                raise CompanionError("没有找到这项预计交付。")
            chosen["format"], chosen["name"] = new_format, str(
                Path(file_name).with_suffix("." + new_format)
            )
            candidate = {
                "id": uuid.uuid4().hex,
                **validate_estimate(raw, self._plan_context),
            }
            self._format_choices.append(
                {"file": file_name, "format": new_format, "result_name": chosen["name"]}
            )
            self.store.event(self.task, "user_format_choice", self._format_choices[-1])
            self.prepared = candidate
            context = {
                **self._plan_context,
                "explicit_ui_format_choices": list(self._format_choices),
            }
        if not candidate["can_prepare"]:
            self._set("planned", "这个交付格式尚未支持。")
            return self.snapshot()

        def compile_choice():
            contract = self.requirements_factory(self.config_at_plan).compile(
                context, candidate, cancelled=self.cancelled
            )
            if self.cancelled.is_set():
                return
            self.prepared = {**candidate, "task_contract": contract}
            self._set("planned", "交付格式与验收已更新，尚未开始。")

        return self._launch(compile_choice, "planning")

    def _output_folder(self):
        root = self.workspace.tree()["root"]
        base = (
            Path(root) / "Koto输出" / self.task[:12]
            if root
            else self.folder / "outputs"
        )
        destination = base / ("v" + str(self.plan_revision))
        if root and not destination.resolve().is_relative_to(Path(root).resolve()):
            raise CompanionError("交付目录不在工作区内。")
        destination.mkdir(parents=True, exist_ok=False)
        return destination

    def execute(self, plan_id):
        prepared = self.prepared
        if not prepared or prepared["id"] != plan_id or not prepared["can_prepare"]:
            raise CompanionError("交付预判不可用或已过期，请更新预判。")
        if not prepared.get("task_contract"):
            raise CompanionError("任务验收尚未登记，请更新预判。")
        if self.phase != "planned":
            raise CompanionError("这份计划已经开始，不能重复开始。")

        def start():
            if self.config_factory() != self.config_at_plan:
                raise DocumentConflict("模型配置已变化，请更新交付预判。")
            if self.workspace.tree()["generation"] != self.generation:
                raise DocumentConflict("工作文件夹已变化，请更新交付预判。")
            self.readers.verify()
            self.document.verify()
            if self.cancelled.is_set():
                return
            self.plan_revision += 1
            self.store.revision = self.plan_revision
            edit_allowed = any(d["kind"] == "edit" for d in prepared["deliveries"])
            expected = [
                d["name"] for d in prepared["deliveries"] if d["kind"] == "create"
            ]
            old = self.store.get(self.task)
            user_goal = {
                "previous_user_requests": self._past_requests,
                "latest_user_request": self.instruction,
                "explicit_ui_format_choices": self._format_choices,
            }
            self.store.change(
                self.task,
                goal=json.dumps(user_goal, ensure_ascii=False),
                expected_outputs=expected,
                plan=[],
                phase="active",
                review=None,
                artifacts={},
                artifact_history=[
                    *old.get("artifact_history", []),
                    *old["artifacts"].values(),
                ],
                ui_plan_revision=self.plan_revision,
                contract_revision=old.get("contract_revision", 0) + 1,
                acceptance_history=[
                    *old.get("acceptance_history", []),
                    {
                        "revision": old.get("ui_plan_revision", 0),
                        **{
                            key: old.get(key, {})
                            for key in (
                                "output_limits",
                                "content_checks",
                                "workbook_schemas",
                                "native_content_checks",
                            )
                        },
                    },
                ],
                output_limits={},
                content_checks={},
                workbook_schemas={},
                native_content_checks={},
                constraints={},
                analyses=[],
                drafts={},
            )
            self.outputs = self._output_folder()
            from .agent_lab.task_requirements import install

            install(
                self.store,
                self.task,
                prepared["task_contract"],
                self.resources,
                self.plan_revision,
                self.workspace,
            )
            workspace = self.workspace
            if not workspace.tree()["root"]:
                workspace = LocalWorkspace()
                empty = self.folder / "references"
                empty.mkdir(exist_ok=True)
                workspace.open(empty)
            broker = NativeBroker(
                self.store,
                self.task,
                workspace,
                self.outputs,
                self.document,
                WriteVerifier(self.config_at_plan, self.store, self.task),
                edit_allowed,
            )
            if not self.engine or self._engine_config != self.config_at_plan:
                if self.engine:
                    self.engine.close()
                self.engine = self.engine_factory(
                    self.config_at_plan, self.folder / "checkpoints.sqlite3"
                )
                self._engine_config = self.config_at_plan
            self.lab = LabSession(self.store, self.task, broker, self.engine)
            self._send(
                (
                    json.dumps(user_goal, ensure_ascii=False)
                    if self._format_choices
                    else self.instruction
                ),
                "start",
            )

        return self._launch(start, "running")

    def _send(self, message, interaction, *, record_request=True):
        if self.cancelled.is_set():
            raise OperationCancelled("已停止，没有开始新的模型回合。")
        state = self.store.get(self.task)
        prior_review = state.get("review")
        prior_edit_count = len(state.get("edits", []))
        broker = self.lab.broker
        broker.selected_sources = list(self.source_ids)
        broker.interaction = interaction
        current_edits = [
            e for e in state["edits"] if e.get("plan_revision") == self.plan_revision
        ]
        covered = broker.processed_fragments()
        if interaction == "feedback":
            checkpoint = state["review"] or (
                current_edits[-1] if current_edits else None
            )
            if not checkpoint:
                raise CompanionError("当前没有可以调整的原文检查点。")
            broker.allowed_fragments = {checkpoint["fragment"]}
        else:
            broker.allowed_fragments = set(self.document.fragments) - covered
        self.turn = message
        readonly = not self.prepared["deliveries"]
        result = self.lab.send(
            message,
            mode="read" if readonly else "auto",
            acknowledge=interaction in ("continue", "feedback"),
            cancelled=self.cancelled,
            interaction=interaction,
            record_request=record_request,
        )
        state = result["state"]
        if (
            interaction == "feedback"
            and prior_review
            and not state.get("review")
            and len(state.get("edits", [])) == prior_edit_count
            and state["phase"] not in ("uncertain", "complete")
            and not self.cancelled.is_set()
        ):
            # The single composer also accepts questions during review. A reply
            # without a native change must not silently acknowledge that review.
            state = self.store.change(self.task, review=prior_review, phase="review")
        self.answer = result["answer"]
        if self.cancelled.is_set():
            self._set(
                "uncertain" if state["phase"] == "uncertain" else "stopped",
                (
                    "结果待核实。"
                    if state["phase"] == "uncertain"
                    else "已停止，已完成内容保留。"
                ),
            )
        elif state["phase"] == "uncertain":
            self._set("uncertain", "有操作结果待核实，不自动重做。")
        elif state["review"]:
            self._set("review", "已在原文更新一处，等你检查。")
        elif state["phase"] == "complete" or readonly:
            self._set(
                "complete" if state["phase"] == "complete" else "answered",
                "已完成。" if not readonly else "",
            )
        else:
            self._set("answered", "本次回复已结束，任务仍可继续。")
        assistant = self.answer or self.message
        turn_id = uuid.uuid4().hex
        self.journal.record(
            self.scope,
            self.task,
            turn_id,
            "turn_completed",
            {"user": message, "assistant": assistant},
        )
        self.history = [
            *self.history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": assistant},
        ][-12:]

    def turn_task(self, message="", interaction="continue"):
        if interaction not in ("continue", "feedback", "message"):
            raise CompanionError("任务操作类型无效。")
        if not self.lab or not self.prepared:
            raise CompanionError("请先预判并开始任务。")
        if not isinstance(message, str) or len(message) > 10000:
            raise CompanionError("反馈应为不超过10000字的文字。")
        if self.workspace.tree()["generation"] != self.generation:
            raise DocumentConflict("工作文件夹已变化，请重新预判。")
        control_only = interaction == "continue" and not message.strip()
        if control_only:
            message = "保留已经检查的结果，继续完成原目标中剩余的修改和全部交付。"
        if not message.strip():
            raise CompanionError("请输入反馈或问题。")
        return self._launch(
            lambda: self._send(
                message.strip(), interaction, record_request=not control_only
            ),
            "running",
        )

    def stop(self):
        self.cancelled.set()
        if self.lab:
            self.lab.stop()
        self._set(
            "stopping" if self.busy else "stopped",
            "正在停止…" if self.busy else "已停止。",
        )
        return self.snapshot()

    def locate(self):
        state = self.store.get(self.task) if self.task else {}
        latest = state.get("review") or (state.get("edits") or [None])[-1]
        if not latest:
            raise CompanionError("尚没有已确认的原文改动。")
        self.documents.locate(self.target.id, latest["fragment"])
        return self.snapshot()

    def open_delivery(self, name):
        state = self.store.get(self.task) if self.task else {}
        receipt = state.get("artifacts", {}).get(name)
        if (
            not receipt
            or not self.outputs
            or FileActions.receipt(self.outputs / name, "verify")["sha256"]
            != receipt["sha256"]
        ):
            raise DocumentConflict("交付文件未生成或已经变化，不能打开旧回执。")
        os.startfile(str(self.outputs / name))
        return {"opened": name}

    def snapshot(self):
        with self.lock:
            state = self.store.get(self.task) if self.task else {}
            if self.task:
                events = self.store.events(self.task, self._event_cursor)
                for e in events:
                    self._event_cursor = e["seq"]
                    activity = public_activity(e)
                    if activity:
                        self.activity.append(activity)
                        self.activity = self.activity[-30:]
                    if e["kind"] == "source_read":
                        self.sources_read[e["body"]["file_id"]] = e["body"]
                    elif e["kind"] == "data_query":
                        for source in e["body"]["sources"]:
                            self.sources_read[source["file_id"]] = {
                                "file_id": source["file_id"],
                                "version": source["sha256"],
                                "method": "query_data",
                                "result_id": e["body"]["result_id"],
                            }
            edits = [
                e
                for e in state.get("edits", [])
                if e.get("plan_revision") == self.plan_revision
            ]
            latest = edits[-1] if edits else None
            artifact_values = list(state.get("artifacts", {}).values())
            index = (
                list(self.document.fragments).index(latest["fragment"])
                if latest and self.document
                else 0
            )
            native_done = len({e["fragment"] for e in edits})
            return {
                "revision": self.revision + self._event_cursor,
                "phase": self.phase,
                "busy": self.busy,
                "message": self.message,
                "unit": "段",
                "target": asdict(self.target) if self.target else None,
                "instruction": self.instruction,
                "turn": self.turn,
                "index": index,
                "shown": native_done,
                "latest": (
                    {
                        **latest,
                        "index": index,
                        "kind": "edited",
                        "note": latest["reason"],
                    }
                    if latest
                    else None
                ),
                "answer": self.answer,
                "history": self.history,
                "history_scope": self.scope or "unbound",
                "conversation": {"task_id": self.task, "phase": self.phase},
                "recovery": self.recovery,
                "artifact": artifact_values[-1] if artifact_values else None,
                "can_continue": bool(
                    self.lab
                    and not self.busy
                    and self.phase
                    not in ("planned", "complete", "uncertain", "conflict")
                ),
                "can_revise": bool(
                    self.lab and not self.busy and self.phase == "review"
                ),
                "can_retry": False,
                "sources": list(self.sources_read.values()),
                "workflow": {
                    "engine": "deepagents",
                    "prepared": self.prepared,
                    "resources": self.resources,
                    "source_ids": self.source_ids,
                    "plan_revision": self.plan_revision,
                    "turn_number": state.get("turn", 0),
                    "steps": state.get("plan", []),
                    "expected_outputs": state.get("expected_outputs", []),
                    "artifacts": artifact_values,
                    "edit_required": bool(self.lab and self.lab.broker.edit_allowed),
                    "sources_read": list(self.sources_read),
                    "activity": list(self.activity),
                    "uncertain": state.get("phase") == "uncertain",
                },
            }

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop()
        self.documents.close()
        if not self.busy and self.engine:
            self.engine.close()
        if not self.busy:
            self.store.close()
