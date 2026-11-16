"""One model-driven editing loop with a human checkpoint after each fragment."""

from dataclasses import asdict
import hashlib
import threading
import uuid

from .contracts import (
    CompanionError,
    DocumentConflict,
    OperationCancelled,
    ResultUncertain,
)
from .agent import AnswerProposal, WorkspaceAgent
from .cell_edits import CellEditProposal, SkipProposal
from .editor_profiles import editor_profile
from .reading import TextSnapshot, DeferredSnapshot
from .workspace import LocalWorkspace
from .journal import EventJournal, document_scope
from .file_actions import FileActionProposal


class EditingSession:
    def __init__(
        self,
        documents,
        model_factory,
        references_factory=None,
        journal=None,
        file_actions=None,
    ):
        self._documents = documents
        self._model_factory = model_factory
        self._references_factory = references_factory or LocalWorkspace().session
        self._agent_mode = False
        self._sources = []
        self._events = []
        self._lock = threading.RLock()
        self._harness = {}
        self._target = None
        self._expected = {}
        self._index = 0
        self._edited_current = False
        self._instruction = ""
        self._turn = ""
        self._host = "auto"
        self._feedback = []
        self._cancel = threading.Event()
        self._epoch = 0
        self._busy = False
        self._phase = "idle"
        self._message = "在 Word 或 WPS 中选择文字，然后连接文档。"
        self._latest = None
        self._revision = 0
        self._answer = ""
        self._history = []
        self._task_history = []
        self._binding_conflict = False
        self._conversation_phase = "idle"
        self._journal = journal or EventJournal()
        self._scope = None
        self._task_id, self._turn_id = uuid.uuid4().hex, uuid.uuid4().hex
        self._recovery = None
        self._journal_seen = set()
        self._file_actions = file_actions
        self._artifact = None

    def _record(self, kind, body=None, action=None):
        self._journal.record(
            self._scope or "unbound:" + self._task_id,
            self._task_id,
            self._turn_id,
            kind,
            body,
            action,
        )

    def restore_history(self, observation):
        scope = document_scope(observation.get("host", ""), observation.get("path"))
        with self._lock:
            if not scope or self._busy or self._target or self._scope == scope:
                return
            self._scope = scope
            self._task_history = []
            recovered = self._journal.recovery(scope)
            self._history = recovered.pop("history")
            self._recovery = (
                recovered if self._history or recovered["unverified"] else None
            )

    def _set(self, phase, message):
        self._phase, self._message = phase, message
        self._revision += 1

    def history_page(self, before=None, query="", limit=20):
        with self._lock:
            scope = self._scope or "unbound:" + self._task_id
        return self._journal.history_page(scope, before, query, limit)

    def _remember_turn(self, user, assistant):
        messages = [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
        self._history = (self._history + messages)[-12:]
        self._task_history = (self._task_history + messages)[-12:]

    def snapshot(self):
        with self._lock:
            target = self._target
            return {
                "revision": self._revision,
                "unit": (
                    editor_profile(target.host, target.fragments[0])["unit"]
                    if target and target.fragments
                    else "段"
                ),
                "phase": self._phase,
                "message": self._message,
                "busy": self._busy,
                "conversation": {
                    "phase": self._conversation_phase,
                    "task_id": self._task_id,
                    "context_turns": len(self._task_history) // 2,
                },
                "recovery": self._recovery,
                "artifact": self._artifact,
                "checkpoint": {
                    "phase": (
                        "conflict"
                        if self._binding_conflict
                        else "review" if self._edited_current else "pending"
                    ),
                    "index": self._index,
                    "binding_valid": not self._binding_conflict,
                },
                "target": asdict(target) if target else None,
                "index": self._index,
                "shown": self._index + int(self._edited_current) if target else 0,
                "latest": dict(self._latest) if self._latest else None,
                "instruction": self._instruction,
                "turn": self._turn or self._instruction,
                "can_retry": bool(
                    self._phase == "error" and not self._busy and self._instruction
                ),
                "answer": self._answer,
                "sources": list(self._sources),
                "events": list(self._events[-30:]),
                "history": list(self._history[-12:]),
                "history_scope": self._scope or "unbound:" + self._task_id,
                "turn_id": self._turn_id,
                "harness": dict(self._harness),
                "can_start": bool(target and self._phase == "bound"),
                "can_continue": bool(
                    target
                    and not self._busy
                    and self._phase in ("review", "stopped", "error")
                ),
                "can_revise": bool(
                    target and not self._busy and self._phase in ("review", "conflict")
                ),
            }

    def connect(self, host, readable=False):
        with self._lock:
            if self._busy:
                raise CompanionError("请等待当前操作结束后再重新绑定文档。")
            self._busy = True
            self._set("connecting", "正在连接原生文档…")
        try:
            target = (
                self._documents.connect_readable(host)
                if readable and hasattr(self._documents, "connect_readable")
                else self._documents.connect(host)
            )
            with self._lock:
                self._target = target
                self._scope = document_scope(target.host, target.path)
                self._task_id = uuid.uuid4().hex
                self._record(
                    "target_bound",
                    {"name": target.name, "fragments": len(target.fragments)},
                )
                self._binding_conflict = False
                self._expected = {
                    fragment.id: fragment.text for fragment in target.fragments
                }
                self._index, self._edited_current = 0, False
                self._instruction, self._feedback, self._latest = "", [], None
                self._task_history, self._recovery = [], None
                self._turn = ""
                self._answer = ""
                self._sources, self._events = [], []
                self._epoch += 1
                self._cancel = threading.Event()
                self._set(
                    "bound", f"已绑定 {target.name}，共 {len(target.fragments)} 处。"
                )
        except Exception as error:
            with self._lock:
                self._target = None
                message = (
                    str(error)
                    if isinstance(error, CompanionError)
                    else "文档连接或执行记录未能准备完成。"
                )
                self._set("error", message)
            raise CompanionError(message) from None
        finally:
            with self._lock:
                self._busy = False
        return self.snapshot()

    def start(self, instruction, agent=False):
        if (
            not isinstance(instruction, str)
            or not instruction.strip()
            or len(instruction) > 10000
        ):
            raise CompanionError("请填写不超过 10000 字的修改要求。")
        with self._lock:
            if self._phase != "bound" or self._busy:
                raise CompanionError("请先重新读取需要修改的选区。")
            model = self._model_factory()
            self._agent_mode = agent
            self._instruction = instruction.strip()
            self._turn = self._instruction
            self._launch(model)
        return self.snapshot()

    def submit(self, instruction, host="auto"):
        """Acknowledge immediately; native binding runs outside the UI request."""
        if (
            not isinstance(instruction, str)
            or not instruction.strip()
            or len(instruction) > 10000
        ):
            raise CompanionError("请填写不超过 10000 字的要求。")
        model = self._model_factory()
        with self._lock:
            if self._busy:
                raise CompanionError("请先停止或等待当前任务完成。")
            self._epoch += 1
            self._task_id, self._turn_id = uuid.uuid4().hex, uuid.uuid4().hex
            self._journal_seen.clear()
            epoch = self._epoch
            self._cancel = cancelled = threading.Event()
            self._busy, self._agent_mode = True, True
            self._target, self._latest, self._answer = None, None, ""
            self._artifact = None
            self._binding_conflict = False
            self._sources, self._events, self._feedback = [], [], []
            self._task_history, self._recovery = [], None
            self._harness = {}
            self._index, self._edited_current = 0, False
            self._instruction = instruction.strip()
            self._turn, self._host = self._instruction, host
            self._set("connecting", "正在读取选中文字…")
            threading.Thread(
                target=self._prepare,
                args=(model, host, epoch, cancelled),
                name="CompanionPrepare",
                daemon=True,
            ).start()
        return self.snapshot()

    def _prepare(self, model, host, epoch, cancelled):
        try:
            if hasattr(self._documents, "bind_current"):
                target = self._documents.bind_current(host)
            else:
                if hasattr(self._documents, "read_current"):
                    host = self._documents.read_current(host)["host"]
                target = self._documents.connect("word" if host == "auto" else host)
            with self._lock:
                if cancelled.is_set() or epoch != self._epoch:
                    raise OperationCancelled("已停止，未调用模型。")
                self._target = target
                self._scope = document_scope(target.host, target.path)
                self._record(
                    "target_bound",
                    {"name": target.name, "fragments": len(target.fragments)},
                )
                self._expected = {f.id: f.text for f in target.fragments}
                self._set("running", "正在思考…")
            self._run(model, target, 0, epoch, cancelled, ())
        except Exception as error:
            with self._lock:
                self._set(
                    "stopped" if cancelled.is_set() else "error",
                    (
                        str(error)
                        if isinstance(error, CompanionError)
                        else "暂时无法读取选区，请稍后重试。"
                    ),
                )
                self._busy = False

    def advance(self, feedback=""):
        with self._lock:
            if (
                self._busy
                or self._phase not in ("review", "stopped", "error")
                or not self._instruction
            ):
                raise CompanionError("当前不能继续，请先连接选区并开始任务。")
            if self._edited_current:
                if self._index + 1 == len(self._target.fragments):
                    self._set(
                        "complete",
                        "所选内容已逐处处理完成，可以在原生应用中继续编辑和保存。",
                    )
                    return self.snapshot()
            model = self._model_factory()
            self._add_feedback(feedback)
            self._turn = feedback.strip() or "保留并继续下一处"
            if self._edited_current:
                self._index += 1
                self._edited_current = False
            self._launch(model)
        return self.snapshot()

    def revise(self, feedback):
        with self._lock:
            if self._busy or self._phase not in ("review", "conflict"):
                raise CompanionError("请等待当前内容处理完成后再调整。")
            if not isinstance(feedback, str) or not feedback.strip():
                raise CompanionError("请写下当前内容需要怎样调整。")
            model = self._model_factory()
            self._turn = feedback.strip()
            self._launch(model, feedback.strip())
        return self.snapshot()

    def retry(self):
        with self._lock:
            if self._busy or self._phase != "error" or not self._instruction:
                raise CompanionError("当前没有可安全重试的请求。")
            if self._target is None:
                return self.submit(self._instruction, self._host)
            self._launch(self._model_factory())
        return self.snapshot()

    def _add_feedback(self, feedback):
        if not isinstance(feedback, str) or len(feedback) > 10000:
            raise CompanionError("反馈需要是不超过 10000 字的文字。")
        if feedback.strip():
            self._feedback.append(feedback.strip())
            if len(self._feedback) > 30:
                self._feedback.pop(0)

    def _launch(self, model, turn_feedback=""):
        # Construct/validate the model before launching work, so invalid config
        # cannot leave a phantom running task or consume a review checkpoint.
        self._epoch += 1
        epoch = self._epoch
        cancelled = threading.Event()
        self._cancel = cancelled
        self._turn_id = uuid.uuid4().hex
        self._journal_seen.clear()
        try:
            self._record("turn_started", {"request": self._turn})
        except Exception:
            self._set("error", "执行记录暂时无法保存，尚未开始新操作。")
            raise CompanionError("执行记录暂时无法保存，尚未开始新操作。") from None
        self._busy = True
        self._answer = ""
        self._conversation_phase = "running"
        target, index = self._target, self._index
        feedback = tuple(self._feedback) + ((turn_feedback,) if turn_feedback else ())
        self._set(
            "running",
            f"正在处理第 {index + 1} / {len(target.fragments)} 处，你可以继续编辑其他位置。",
        )
        threading.Thread(
            target=self._run,
            args=(model, target, index, epoch, cancelled, feedback),
            name="CompanionAgent",
            daemon=True,
        ).start()

    def _run(self, model, target, index, epoch, cancelled, feedback):
        fragment = target.fragments[index]
        current = self._expected[fragment.id]
        edit_prepared = False
        native_applied = False

        def permitted():
            with self._lock:
                return not cancelled.is_set() and epoch == self._epoch

        def progress(name, file_id):
            with self._lock:
                if not permitted():
                    raise OperationCancelled("已停止。")
                if name == "answer_delta":
                    self._answer = file_id
                    self._set("running", "正在回答…")
                    return
                if name == "harness_state":
                    self._harness = file_id
                    event = (file_id.get("events") or [None])[-1]
                    key = (file_id.get("id"), str(event))
                    if event and key not in self._journal_seen:
                        self._journal_seen.add(key)
                        self._record(
                            "agent_event", {"event": event, "goal": file_id.get("goal")}
                        )
                    self._revision += 1
                    return
                if name == "model_retry":
                    self._answer = ""
                    self._set("running", "接口暂时未响应，正在重试…")
                    return
                self._events.append({"tool": name, "file_id": file_id})
                self._events = self._events[-30:]
                self._set(
                    "running",
                    ("正在读取 " + file_id if file_id else "正在核对文档和资料…"),
                )

        def prepare_edit():
            nonlocal current, edit_prepared
            if not permitted():
                raise OperationCancelled("已停止，未读取编辑目标。")
            actual = self._documents.read(target.id, fragment.id)
            if actual != self._expected[fragment.id]:
                expected = self._expected[fragment.id]
                with self._lock:
                    self._events.append(
                        {
                            "tool": "target_read_conflict",
                            "stage": "before_edit",
                            "fragment": fragment.id,
                            "index": index,
                            "expected_length": len(expected),
                            "actual_length": len(actual),
                            "expected_hash": hashlib.sha256(
                                expected.encode("utf-8")
                            ).hexdigest(),
                            "actual_hash": hashlib.sha256(
                                actual.encode("utf-8")
                            ).hexdigest(),
                            "origin": "unknown",
                            "native_binding": dict(
                                getattr(self._documents, "last_read", None) or {}
                            ),
                        }
                    )
                raise DocumentConflict(
                    "绑定片段的读取结果与上次确认不一致，已暂停；请检查原文后重新读取选区。"
                )
            current, edit_prepared = actual, True
            return {
                "current_text": current,
                "document_context": (
                    self._documents.agent_context(target.id)
                    if self._agent_mode and hasattr(self._documents, "agent_context")
                    else (
                        self._documents.context(target.id)
                        if hasattr(self._documents, "context")
                        else target.context
                    )
                ),
            }

        def selected_snapshot():
            texts = []
            for selected in target.fragments:
                if not permitted():
                    raise OperationCancelled("已停止读取选区。")
                texts.append(self._documents.read(target.id, selected.id))
            return TextSnapshot(
                target.name + " · 绑定选区",
                "\n".join(texts),
                (f"原生绑定选区，共{len(texts)}处",),
                ("仅覆盖任务开始时绑定的选区，不跟随之后移动的光标",),
            )

        try:
            legacy_context = None
            if not self._agent_mode:
                legacy_context = prepare_edit()["document_context"]
            elif not isinstance(model, WorkspaceAgent) and hasattr(
                self._documents, "context"
            ):
                legacy_context = self._documents.context(target.id)
            arguments = dict(
                original=fragment.text,
                current=current,
                instruction=self._instruction,
                feedback=feedback,
                index=index,
                total=len(target.fragments),
                cancelled=cancelled,
                context=(
                    legacy_context
                    if legacy_context is not None
                    else {
                        "selection": {
                            "active": True,
                            "text": "\n".join(
                                self._expected[f.id] for f in target.fragments
                            )[:12000],
                            "fragment_count": len(target.fragments),
                            "truncated": sum(
                                len(self._expected[f.id]) + 1 for f in target.fragments
                            )
                            - 1
                            > 12000,
                            "freshness": "task_binding_and_verified_edits_not_live",
                        },
                        "checkpoint_context": {
                            "freshness": "last_verified_not_live",
                            "latest": self._latest,
                            "binding_conflict": self._binding_conflict,
                        },
                    }
                ),
            )
            references = None
            if self._agent_mode:
                references = self._references_factory()
                document = (
                    DeferredSnapshot(
                        target.name, lambda: self._documents.text_snapshot(target.id)
                    )
                    if hasattr(self._documents, "text_snapshot")
                    else TextSnapshot(
                        target.name,
                        "\n".join(f.text for f in target.fragments),
                        ("当前选区",),
                        ("连接器未提供全文读取",),
                    )
                )
                proposal = model.step(
                    **arguments,
                    document=document,
                    references=references,
                    progress=progress,
                    editable=fragment.editable,
                    history=list(self._task_history),
                    checkpoint=dict(self._harness),
                    editor=editor_profile(target.host, fragment),
                    **(
                        {
                            "prepare_edit": prepare_edit,
                            "file_actions": self._file_actions,
                            "history_reader": self.history_page,
                            "selection": DeferredSnapshot(
                                target.name + " · 绑定选区", selected_snapshot
                            ),
                        }
                        if isinstance(model, WorkspaceAgent)
                        else {}
                    ),
                )
            else:
                proposal = model.propose(**arguments)
            if not permitted():
                raise OperationCancelled("已停止，旧修改没有写入文档。")
            if references:
                references.verify()
                with self._lock:
                    self._sources = references.evidence()
            if isinstance(proposal, FileActionProposal):
                if not self._file_actions:
                    raise CompanionError("当前未接入文件操作。")
                action_id = uuid.uuid4().hex
                with self._journal.document_lock(self._scope or target.id):
                    self._record(
                        "write_requested",
                        {
                            "action": proposal.action,
                            "name": proposal.arguments.get("file_name", target.name),
                        },
                        action_id,
                    )
                    try:
                        receipt = self._file_actions.execute(
                            proposal, target, permitted, progress
                        )
                    except (CompanionError, OperationCancelled) as error:
                        if not isinstance(error, ResultUncertain):
                            self._record(
                                "write_rejected", {"action": proposal.action}, action_id
                            )
                        raise
                    native_applied = True
                    self._record("write_verified", {"artifact": receipt}, action_id)
                with self._lock:
                    self._artifact = receipt
                    self._answer = (
                        {
                            "create_office_file": "已生成 ",
                            "save_current_document": "已保存 ",
                            "export_current_pdf": "已导出 ",
                        }[proposal.action]
                        + receipt["name"]
                        + "。"
                    )
                    self._remember_turn(self._turn, self._answer)
                    self._record(
                        "turn_completed",
                        {"user": self._turn, "assistant": self._answer},
                    )
                    self._conversation_phase = "answered"
                    self._set(
                        (
                            "conflict"
                            if self._binding_conflict
                            else "review" if self._edited_current else "answered"
                        ),
                        "文件结果已验证。",
                    )
                return
            if isinstance(proposal, AnswerProposal):
                with self._lock:
                    if not permitted():
                        raise OperationCancelled("已停止本次回答。")
                    self._answer = proposal.text
                    self._record(
                        "turn_completed",
                        {"user": self._turn, "assistant": proposal.text},
                    )
                    self._conversation_phase = "answered"
                    self._remember_turn(self._turn or self._instruction, proposal.text)
                    self._set(
                        (
                            "conflict"
                            if self._binding_conflict
                            else (
                                "review"
                                if self._edited_current and self._latest
                                else "answered"
                            )
                        ),
                        (
                            "已回答，已完成的修改保留，可以继续后续内容。"
                            if self._edited_current
                            else "已回答，文档未改动。"
                        ),
                    )
                return
            if not edit_prepared:
                prepare_edit()
            skipped = isinstance(proposal, SkipProposal)
            if skipped:
                actual = self._documents.read(target.id, fragment.id)
                if actual != current or not permitted():
                    raise DocumentConflict("当前内容已变化，不能按旧内容保留。")
            else:
                action_id = uuid.uuid4().hex
                with self._journal.document_lock(self._scope or target.id):
                    prepare_edit()
                    self._record(
                        "write_requested",
                        {
                            "name": target.name,
                            "index": index,
                            "fragment": fragment.id,
                            "expected_hash": hashlib.sha256(
                                current.encode("utf-8")
                            ).hexdigest(),
                        },
                        action_id,
                    )
                    try:
                        if isinstance(proposal, CellEditProposal):
                            actual = self._documents.replace_cell(
                                target.id,
                                fragment.id,
                                current,
                                proposal.value_type,
                                proposal.value,
                                permitted,
                            )
                        else:
                            actual = self._documents.replace(
                                target.id,
                                fragment.id,
                                current,
                                proposal.text,
                                permitted,
                            )
                        native_applied = True
                    except (DocumentConflict, OperationCancelled):
                        self._record("write_rejected", {"index": index}, action_id)
                        raise
                    try:
                        self._record(
                            "write_verified",
                            {
                                "index": index,
                                "before": current,
                                "after": actual,
                                "name": target.name,
                                "native_binding": dict(
                                    getattr(self._documents, "last_read", None) or {}
                                ),
                            },
                            action_id,
                        )
                    except Exception:
                        raise ResultUncertain(
                            "宿主已返回写入结果，但执行记录未能保存；请核对文档，本次不会自动重试。"
                        ) from None
            with self._lock:
                self._answer = ""
                self._conversation_phase = "complete"
                self._binding_conflict = False
                self._feedback = list(feedback)
                self._expected[fragment.id] = actual
                self._edited_current = True
                self._latest = {
                    "index": index,
                    "before": current,
                    "after": actual,
                    "note": proposal.reason if skipped else proposal.note,
                    "kind": "skipped" if skipped else fragment.kind,
                    "label": fragment.label,
                }
                self._events.append(
                    {
                        "tool": (
                            "fragment_kept_verified"
                            if skipped
                            else "native_write_verified"
                        ),
                        "index": index,
                    }
                )
                self._harness = {
                    **self._harness,
                    "phase": "review",
                    "verified_fragment": index,
                    "verification": (
                        "unchanged_readback" if skipped else "native_readback_exact"
                    ),
                    "waiting_for": "user_feedback",
                    "scope_verification": (
                        getattr(self._documents, "last_read", None) or {}
                    ).get("scope_verification", "fragment_readback_only"),
                }
                if self._agent_mode:
                    self._remember_turn(
                        self._turn or self._instruction,
                        f"已在 {target.name} 的{fragment.label}{'保留并核对' if skipped else '写入并读回'}：{actual[:2000]}\n参考："
                        + "、".join(source["file_id"] for source in self._sources),
                    )
                    self._record(
                        "turn_completed",
                        {
                            "user": self._turn or self._instruction,
                            "assistant": self._history[-1]["content"],
                        },
                    )
                if cancelled.is_set():
                    self._set(
                        "stopped",
                        "进行中的这一处已经完成，后续写入已停止。请查看实际修改。",
                    )
                else:
                    unit = editor_profile(target.host, fragment)["unit"]
                    self._set(
                        "review",
                        f"第 {index + 1} 个{unit}{'已保留' if skipped else '已显示'}，等你检查。",
                    )
        except ResultUncertain as error:
            with self._lock:
                self._set("uncertain", str(error))
        except DocumentConflict as error:
            with self._lock:
                self._answer = ""
                self._binding_conflict = True
                self._conversation_phase = "error"
                self._harness = {
                    **self._harness,
                    "phase": "conflict",
                    "waiting_for": "check_binding_or_sources",
                }
                if self._latest:
                    self._harness["verification_scope"] = "previous_checkpoint"
                self._set("conflict", str(error))
        except OperationCancelled as error:
            with self._lock:
                self._set("stopped", str(error))
        except Exception as error:
            with self._lock:
                message = (
                    str(error)
                    if isinstance(error, CompanionError)
                    else "当前内容未能处理完成，请检查连接或调整要求后重试。"
                )
                self._set(
                    (
                        "uncertain"
                        if native_applied
                        else "stopped" if cancelled.is_set() else "error"
                    ),
                    (
                        "宿主已返回修改结果，但后续记录未完成；请检查文档，不会自动重试。"
                        if native_applied
                        else message
                    ),
                )
        finally:
            with self._lock:
                self._busy = False
                self._revision += 1

    def ask(self, instruction, context):
        if (
            not isinstance(instruction, str)
            or not instruction.strip()
            or len(instruction) > 10000
        ):
            raise CompanionError("请填写不超过 10000 字的问题。")
        with self._lock:
            if self._busy:
                raise CompanionError("请先停止或等待当前任务完成。")
            model = self._model_factory()
            has_task = self._target is not None and bool(self._instruction)
            restore_phase = self._phase if has_task else "answered"
            if not has_task:
                self._target, self._latest = None, None
                self._index, self._edited_current = 0, False
                self._instruction = instruction.strip()
            self._answer = ""
            self._turn = instruction.strip()
            self._turn_id = uuid.uuid4().hex
            self._cancel = cancelled = threading.Event()
            self._epoch += 1
            epoch = self._epoch
            self._busy = True
            self._conversation_phase = "running"
            self._set("running", "正在阅读当前文档和表格…")
            threading.Thread(
                target=self._answer_question,
                args=(model, instruction, context, epoch, cancelled, restore_phase),
                daemon=True,
                name="CompanionReader",
            ).start()
        return self.snapshot()

    def _answer_question(
        self, model, instruction, context, epoch, cancelled, restore_phase
    ):
        try:
            answer = model.answer(
                instruction=instruction,
                context=context,
                history=list(self._task_history),
                cancelled=cancelled,
            )
            with self._lock:
                if cancelled.is_set() or epoch != self._epoch:
                    raise OperationCancelled("已停止本次回答。")
                self._answer = answer
                self._conversation_phase = "answered"
                self._record(
                    "turn_completed", {"user": instruction, "assistant": answer}
                )
                self._remember_turn(instruction, answer)
                self._set(restore_phase, "已结合当前文档回答，编辑检查点保留。")
        except Exception as error:
            with self._lock:
                self._set(
                    "stopped" if cancelled.is_set() else "error",
                    (
                        str(error)
                        if isinstance(error, CompanionError)
                        else "回答未完成，请稍后重试。"
                    ),
                )
        finally:
            with self._lock:
                self._busy = False
                self._revision += 1

    def stop(self):
        with self._lock:
            self._epoch += 1
            self._cancel.set()
            self._set(
                "stopping" if self._busy else "stopped",
                (
                    "已停止当前任务，等待进行中的请求结束。"
                    if self._busy
                    else "已停止，已经完成的内容保留。"
                ),
            )
        return self.snapshot()

    def locate(self):
        with self._lock:
            if not self._target:
                raise CompanionError("请先连接文档。")
            target = self._target
            index = self._latest["index"] if self._latest else self._index
            fragment = target.fragments[index]
        self._documents.locate(target.id, fragment.id)

    def close(self):
        self.stop()
        self._documents.close()
