"""Typed CNY scale conversions and checks against the final proposed fragment.

This is a registered arithmetic capability, not free-text intent routing.
It does not exchange currencies or establish that a source fact is correct.
"""

from decimal import Decimal, localcontext
import re

from .contracts import CompanionError

UNIT_SCALES = {
    "元": 0,
    "yuan": 0,
    "千元": 3,
    "thousand yuan": 3,
    "万元": 4,
    "ten thousand yuan": 4,
    "百万元": 6,
    "million yuan": 6,
    "亿元": 8,
    "hundred million yuan": 8,
}


class QuantityLedger:
    def __init__(self):
        self.results = {}

    def convert(self, value, from_unit, to_unit):
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[+-]?\d{1,20}(?:\.\d{1,12})?", value)
            or from_unit not in UNIT_SCALES
            or to_unit not in UNIT_SCALES
        ):
            raise CompanionError(
                "请提供十进制金额及支持的人民币单位；本工具不兑换币种。"
            )
        if len(self.results) >= 16:
            raise CompanionError("本轮单位换算过多，请缩小范围。")
        with localcontext() as context:
            context.prec = 64
            result = Decimal(value) * Decimal(10) ** (
                UNIT_SCALES[from_unit] - UNIT_SCALES[to_unit]
            )
        text = format(result, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        quantity_id = "q" + str(len(self.results) + 1)
        proof = {
            "quantity_id": quantity_id,
            "source": {"value": value, "unit": from_unit},
            "target": {"value": text, "unit": to_unit},
            "instruction": "写入时使用目标数值和目标单位，在 quantity_checks 中引用此编号；不能把源数值配上目标单位。",
        }
        self.results[quantity_id] = proof
        return proof

    def verify(self, text, quantity_checks):
        if self.results and not quantity_checks:
            raise CompanionError(
                "已执行单位换算，请在 quantity_checks 中列出正文实际采用的换算编号，先核对后再修改。"
            )
        normalized = re.sub(r"(?<=\d)[,，](?=\d{3}(?:\D|$))", "", text)
        normalized = re.sub(r"\s+", "", normalized)
        for identifier in quantity_checks:
            proof = self.results.get(identifier)
            if not proof:
                raise CompanionError("换算编号不存在，请先调用单位换算工具。")
            expected = proof["target"]
            aliases = [
                re.sub(r"\s+", "", name)
                for name, scale in UNIT_SCALES.items()
                if scale == UNIT_SCALES[expected["unit"]]
            ]
            pattern = (
                r"(?<![\d.])([+-]?\d+(?:\.\d+)?)((?:"
                + "|".join(
                    re.escape(name) for name in sorted(aliases, key=len, reverse=True)
                )
                + r"))"
            )
            if not any(
                Decimal(match.group(1)) == Decimal(expected["value"])
                for match in re.finditer(pattern, normalized)
            ):
                raise CompanionError(
                    f"换算核对未通过：{identifier} 应为 {expected['value']} {expected['unit']}。请修正文案中的数值和单位；修改尚未执行。"
                )
