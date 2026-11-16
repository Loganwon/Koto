"""A model-declared task destination gates the native editing capabilities.

This is a tool protocol, not a free-text intent classifier. Each user turn
starts without edit authority; plans and previous successful writes cannot
grant authority for a different requested output.
"""

from .contracts import CompanionError

GOAL_TOOL = {
    "type": "function",
    "function": {
        "name": "declare_task_goal",
        "description": (
            "Before proposing any native edit, identify the user's requested final "
            "destination and operation, using the request and latest feedback only. "
            "A request for a new PPT/file has target=new_file and operation=create, "
            "even when the selected Word paragraph says '待补充'. Do not downgrade "
            "a missing capability into editing the current paragraph. Read-only "
            "answers need no declaration. This declaration is fixed for this turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": [
                        "current_fragment",
                        "reference_file",
                        "new_file",
                        "none",
                    ],
                },
                "operation": {
                    "type": "string",
                    "enum": [
                        "edit",
                        "answer",
                        "create",
                        "save",
                        "export",
                        "organize",
                        "deliver",
                        "format",
                    ],
                },
                "summary": {"type": "string", "minLength": 1, "maxLength": 250},
            },
            "required": ["target", "operation", "summary"],
            "additionalProperties": False,
        },
    },
}


class TaskGoal:
    def __init__(self, editable):
        self.editable = editable
        self.value = None

    @property
    def can_edit(self):
        return bool(
            self.editable
            and self.value
            and self.value["target"] == "current_fragment"
            and self.value["operation"] == "edit"
        )

    def declare(self, target, operation, summary):
        if self.value is not None:
            raise CompanionError(
                "本轮目标已确认，不能为取得写入工具而改换目标。请回答实际能力限制。"
            )
        self.value = {"target": target, "operation": operation, "summary": summary}
        return {
            **self.value,
            "native_edit_available": self.can_edit,
            "instruction": (
                "可以按当前目标提出一个片段的修改，原生读回后等待用户反馈。"
                if self.can_edit
                else "本轮不开放当前片段写入。可使用已经提供、且符合本轮目标的文件工具；没有对应工具时只读核对并说明未完成，不得把任务改成替用户修改当前文档。"
            ),
        }

    def check_edit(self):
        if not self.can_edit:
            raise CompanionError(
                "本轮尚未确认可执行的当前片段编辑目标；修改没有执行。请先确认用户要求的实际目标，不得用修改当前段落代替生成、保存或交付其他文件。"
            )

    def allows(self, spec):
        if spec.name in (
            "create_office_file",
            "save_current_document",
            "export_current_pdf",
        ):
            return self.can_file(spec.name)
        if spec.name == "declare_task_goal":
            return self.value is None
        if spec.effect == "proposal" or spec.name == "skip_current_fragment":
            return self.can_edit
        return True

    def can_file(self, name):
        requested = {
            "create_office_file": ("new_file", "create"),
            "save_current_document": ("current_fragment", "save"),
            "export_current_pdf": ("current_fragment", "export"),
        }.get(name)
        return bool(
            requested
            and self.value
            and (self.value["target"], self.value["operation"]) == requested
        )
