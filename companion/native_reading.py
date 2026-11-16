"""On-demand complete native text snapshots; COM stays on the document actor."""

import os

from .contracts import DocumentConflict
from .reading import TextSnapshot

STORIES = {
    2: "脚注",
    3: "尾注",
    4: "批注",
    5: "文本框",
    6: "偶数页页眉",
    7: "页眉",
    8: "偶数页页脚",
    9: "页脚",
    10: "首页页眉",
    11: "首页页脚",
}


def native_snapshot(document):
    # Content includes every body paragraph and table, without the monitor's
    # excerpt limit. Other story ranges are explicit, separately labelled areas.
    blocks = [
        "[正文（含表格）]\n"
        + document.Content.Text.replace("\x07", "\t").replace("\r", "\n")
    ]
    coverage, limitations = ["正文（含表格）"], ["图片未 OCR；嵌入对象未解析"]
    for kind, label in STORIES.items():
        try:
            part = document.StoryRanges.Item(kind)
        except Exception:
            # Word uses the same error for an absent story and an unsupported
            # story. Do not claim these areas have been read in either case.
            continue
        count = 0
        while part is not None:
            count += 1
            if count > 1000:
                limitations.append(label + "区域过多，未全部读取")
                break
            blocks.append(
                f"[{label} {count}]\n"
                + part.Text.replace("\x07", "\t").replace("\r", "\n")
            )
            if label not in coverage:
                coverage.append(label)
            try:
                part = part.NextStoryRange
            except Exception:
                limitations.append(label + "后续区域无法读取")
                break
    limitations.append("覆盖范围以 coverage 为准；宿主未提供的区域不可读")
    return TextSnapshot(
        document.Name, "\n".join(blocks), tuple(coverage), tuple(limitations)
    )


class NativeReading:
    def text_snapshot(self, target_id):
        return self._call("text_snapshot", target_id)

    def _text_snapshot(self, target_id):
        if target_id != self._target_id or self._document is None:
            raise DocumentConflict("文档绑定已变化，请重新读取选区。")
        return native_snapshot(self._document)

    def read_open_file(self, path):
        return self._call("read_open_file", path)

    def _read_open_file(self, path):
        requested = os.path.normcase(os.path.abspath(path))
        for application in self._applications.values():
            for index in range(1, application.Documents.Count + 1):
                document = application.Documents.Item(index)
                if (
                    document.Path
                    and os.path.normcase(os.path.abspath(document.FullName))
                    == requested
                ):
                    return native_snapshot(document)
        return None
