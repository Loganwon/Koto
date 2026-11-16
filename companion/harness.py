"""Provider-neutral harness primitives: capabilities, plans, evidence, recovery.

Only registered tools can execute. Tool results are data; this runtime never
executes Python or a shell expression supplied by a model.
"""

import ast
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import operator
import time
import uuid

from .contracts import CompanionError
from .quantities import QuantityLedger


def validate(value, schema, path="arguments"):
    kind = schema.get("type")
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    if kind in types and (
        not isinstance(value, types[kind])
        or kind in ("integer", "number")
        and isinstance(value, bool)
    ):
        raise CompanionError(f"{path} 类型应为 {kind}。")
    if "enum" in schema and value not in schema["enum"]:
        raise CompanionError(f"{path} 不在允许的选项中。")
    if kind == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", ())) - value.keys()
        if missing:
            raise CompanionError(f"{path} 缺少必要参数：" + ", ".join(sorted(missing)))
        if (
            schema.get("additionalProperties") is False
            and value.keys() - properties.keys()
        ):
            unknown = ", ".join(
                str(k)[:60]
                for k in sorted(value.keys() - properties.keys(), key=str)[:5]
            )
            raise CompanionError(
                f"{path} 包含不支持的参数：{unknown}。支持：" + ", ".join(properties)
            )
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], path + "." + key)
    if kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise CompanionError(f"{path} 项目数超出范围。")
        for item in value:
            validate(item, schema.get("items", {}), path + "[]")
    if kind == "string" and not schema.get("minLength", 0) <= len(value) <= schema.get(
        "maxLength", 18000
    ):
        raise CompanionError(f"{path} 长度超出范围。")
    if kind in ("integer", "number") and not schema.get(
        "minimum", -1e30
    ) <= value <= schema.get("maximum", 1e30):
        raise CompanionError(f"{path} 数值超出范围。")


@dataclass(frozen=True)
class ToolSpec:
    definition: dict
    handler: object = None
    effect: str = "read"

    @property
    def name(self):
        return self.definition["function"]["name"]


class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, spec):
        if spec.name in self.tools:
            raise ValueError("Duplicate tool: " + spec.name)
        if spec.effect not in ("read", "state", "proposal", "answer"):
            raise ValueError("Unsupported tool effect")
        self.tools[spec.name] = spec

    def check(self, name, args):
        if name not in self.tools:
            raise CompanionError("当前宿主未提供此工具，请使用已列出的能力。")
        spec = self.tools[name]
        validate(args, spec.definition["function"]["parameters"])
        return spec

    def definitions(self):
        return [spec.definition for spec in self.tools.values()]


def calculate(expression):
    if not isinstance(expression, str) or not 0 < len(expression) <= 300:
        raise CompanionError("计算表达式需在 300 字以内。")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
    }
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError()

        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                result = Decimal(ast.get_source_segment(expression, node))
            elif isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.UAdd, ast.USub)
            ):
                result = visit(node.operand) * (
                    -1 if isinstance(node.op, ast.USub) else 1
                )
            elif isinstance(node, ast.BinOp) and type(node.op) in operations:
                result = operations[type(node.op)](visit(node.left), visit(node.right))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "round"
                and not node.keywords
                and len(node.args) == 2
                and isinstance(node.args[1], ast.Constant)
                and type(node.args[1].value) is int
                and 0 <= node.args[1].value <= 12
            ):
                from decimal import ROUND_HALF_UP

                result = visit(node.args[0]).quantize(
                    Decimal(1).scaleb(-node.args[1].value), rounding=ROUND_HALF_UP
                )
            else:
                raise ValueError()
            if not result.is_finite() or abs(result) > Decimal("1e30"):
                raise ValueError()
            return result

        with localcontext() as context:
            context.prec = 28
            result = visit(tree.body)
        return {
            "expression": expression,
            "result": str(result),
            "precision": "28 decimal digits",
        }
    except (SyntaxError, ValueError, InvalidOperation, ArithmeticError, RecursionError):
        raise CompanionError(
            "仅支持数字、括号、+ - * / % 及 round(数字表达式,0至12位)，四舍五入使用ROUND_HALF_UP。"
        ) from None


class HarnessRun:
    def __init__(self, progress, checkpoint=None):
        self.id = uuid.uuid4().hex
        self.progress = progress
        self.plan = list((checkpoint or {}).get("plan", []))
        self.events = []
        self.evidence = {}
        self.counts = Counter()
        self.failures = 0
        self.rounds = 0
        self.phase = "running"
        self.goal = None
        self.quantities = QuantityLedger()

    def emit(self, kind, **metadata):
        # Events contain control metadata only, never tool arguments or raw files.
        self.events.append({"type": kind, "time": time.time(), **metadata})
        self.progress("harness_state", self.snapshot())

    def snapshot(self):
        return {
            "id": self.id,
            "phase": self.phase,
            "goal": self.goal,
            "rounds": self.rounds,
            "plan": self.plan,
            "events": self.events[-40:],
            "evidence_count": len(self.evidence),
            "recoveries": self.failures,
        }

    def update_plan(self, steps):
        if sum(step["status"] == "in_progress" for step in steps) > 1:
            raise CompanionError("一次只推进一个计划步骤。")
        self.plan = steps
        self.emit("plan_updated", count=len(steps))
        return {
            "plan": self.plan,
            "checkpoint": "每次原生修改后等待用户；completed 仅代表模型的计划状态，写入以宿主验证为准。",
        }

    def remember(self, name, args, result):
        body = json.dumps(result, ensure_ascii=False)
        fingerprint = hashlib.sha256(
            (name + json.dumps(args, sort_keys=True) + body).encode()
        ).hexdigest()
        self.counts[fingerprint] += 1
        if self.counts[fingerprint] > 3:
            raise CompanionError(
                "同一工具连续返回相同结果，已暂停；请补充要求或换一个查找方向。"
            )
        if len(body) <= 6000:
            return body
        evidence_id = "e" + str(len(self.evidence) + 1)
        self.evidence[evidence_id] = body
        return json.dumps(
            {
                "evidence_id": evidence_id,
                "characters": len(body),
                "preview": body[:2400],
                "notice": "工具结果已暂存；用 read_evidence 分页读取原始结果，不能将预览视为完整内容。",
            },
            ensure_ascii=False,
        )

    def read_evidence(self, evidence_id, start=0, limit=6000):
        if evidence_id not in self.evidence:
            raise CompanionError("未找到本轮证据，请重新读取来源。")
        body = self.evidence[evidence_id]
        return {
            "text": body[start : start + limit],
            "next": start + limit if start + limit < len(body) else None,
            "evidence_id": evidence_id,
            "characters": len(body),
        }

    def compact(self, messages, registry):
        # Keep system/user request and all tool-call/result pairs valid. Replace
        # old read outputs with retrievable evidence, never an invented summary.
        size = sum(len(str(item.get("content") or "")) for item in messages)
        if size <= 42000:
            return
        for message in messages[:-4]:
            if message.get("role") != "tool" or len(message.get("content", "")) < 1500:
                continue
            body = message["content"]
            evidence_id = "e" + str(len(self.evidence) + 1)
            self.evidence[evidence_id] = body
            message["content"] = json.dumps(
                {
                    "evidence_id": evidence_id,
                    "notice": "早期结果已移出上下文；需要时调用 read_evidence。",
                },
                ensure_ascii=False,
            )
            size -= len(body)
            if size <= 30000:
                break
        self.emit("context_compacted")
