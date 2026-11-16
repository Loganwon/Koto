"""Native binding adapter. Only an already-bound host may supply these handles."""

from companion.contracts import CompanionError, ResultUncertain, validate_replacement


class BoundTextDocument:
    """No COM globals, new windows, disk DOCX rewrites or automatic rebinding."""

    native_editor = True

    def __init__(self, port, target):
        if not target.fragments:
            raise CompanionError("没有绑定可读取的片段。")
        self.port, self.target = port, target
        self.fragments = {f.id: f for f in target.fragments}

    def read(self, fragment):
        if fragment not in self.fragments:
            raise CompanionError("这个片段不在绑定范围内。")
        return self.port.read(self.target.id, fragment)

    def contents(self):
        return {key: self.read(key) for key in self.fragments}

    def replace(self, fragment, expected, replacement, permitted):
        unit = self.fragments.get(fragment)
        if not unit or not unit.editable or unit.kind != "text":
            raise CompanionError("当前绑定片段不允许文本替换。")
        validate_replacement(replacement)
        if not permitted():
            raise CompanionError("已停止，没有提交写入。")
        actual = self.port.replace(
            self.target.id, fragment, expected, replacement, permitted
        )
        try:
            readback = self.port.read(self.target.id, fragment)
        except Exception as error:
            raise ResultUncertain(
                "宿主可能已经写入，但读回未完成；需核对，不自动重试。"
            ) from error
        if actual != replacement or readback != replacement:
            raise ResultUncertain("宿主写入后的读回不一致，需核对；不会自动重试。")
        return readback
