"""Explicit cell types and a bounded, local formula dialect."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re

from .contracts import CompanionError, validate_replacement
from .model import EditProposal

LOCAL_FUNCTIONS = frozenset(
    "SUM AVERAGE MIN MAX COUNT COUNTA IF IFERROR ROUND ROUNDUP ROUNDDOWN ABS SUMIF SUMIFS COUNTIF COUNTIFS AND OR NOT CONCAT TEXTJOIN LEN LEFT RIGHT MID TRIM UPPER LOWER TODAY DATE YEAR MONTH DAY".split()
)


@dataclass(frozen=True)
class CellEditProposal(EditProposal):
    value_type: str
    value: str


@dataclass(frozen=True)
class SkipProposal:
    reason: str


def cell_proposal(value_type, value, note):
    if not isinstance(value, str) or not isinstance(note, str) or len(note) > 500:
        raise CompanionError("请给出单个单元格的完整值及简短说明。")
    validate_replacement(value)
    if value_type == "number":
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d{1,3})?", value):
            raise CompanionError("数字单元格需要十进制数字，不能包含单位或千位逗号。")
        try:
            amount = Decimal(value)
            if (
                not amount.is_finite()
                or not math.isfinite(float(amount))
                or (amount and not float(amount))
                or len(amount.normalize().as_tuple().digits) > 15
            ):
                raise ValueError()
        except (InvalidOperation, ValueError, OverflowError):
            raise CompanionError(
                "数字超过当前Excel写入精度或范围，请不要静默舍入。"
            ) from None
    elif value_type == "boolean":
        if value not in ("true", "false"):
            raise CompanionError("布尔值只能为 true 或 false。")
    elif value_type == "formula":
        if not value.startswith("=") or len(value) > 2000:
            raise CompanionError("公式需要以等号开头，且不超过2000字符。")
        if any(token in value for token in ("[", "]", "|", "\\")):
            raise CompanionError(
                "本版公式仅操作本工作簿，暂不支持外部链接、结构化引用或DDE。"
            )
        without_strings = re.sub(r'"(?:[^"]|"")*"', '""', value)
        functions = set(re.findall(r"([A-Za-z_][A-Za-z_0-9.]*)\s*\(", without_strings))
        if any(name.upper() not in LOCAL_FUNCTIONS for name in functions):
            raise CompanionError(
                "该公式包含尚未开放的函数，请使用已支持的本地计算函数。"
            )
    elif value_type == "text":
        if value.lstrip().startswith(("=", "+", "-", "@")):
            raise CompanionError(
                "文本以公式符号开头，本版拒绝隐式公式；请改写文本或明确使用数字/公式类型。"
            )
    else:
        raise CompanionError("单元格类型应为 text、number、boolean 或 formula。")
    return CellEditProposal(value, note, value_type, value)
