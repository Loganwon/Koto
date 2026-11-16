"""Conservative unit provenance from SQL syntax and explicit source headers.

This is a data contract, not interpretation of a natural-language task. Unknown
expressions stay unknown; the caller must not promote them to a currency unit.
"""

from decimal import Decimal
import re

SCALES = {
    "分": Decimal(".01"),
    "元": Decimal(1),
    "千元": Decimal(1000),
    "万元": Decimal(10000),
    "百万元": Decimal(1000000),
    "亿元": Decimal(100000000),
}


def header_unit(name):
    match = re.search(r"[（(](分|元|千元|万元|百万元|亿元|%)[）)]$", name)
    if match:
        return match[1]
    # Explicit amount-in-cents columns are common exported data, not output aliases.
    if name in {"金额分", "单价分", "合计分", "金额元", "单价元"}:
        return name[-1]
    return None


def infer_units(sql, inputs, output_columns):
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.qualify import qualify
    from sqlglot.optimizer.scope import Scope, traverse_scope

    unknown = {name: None for name in output_columns}
    schema = {s["name"]: {c: "UNKNOWN" for c in s["columns"]} for s in inputs}
    sources = {
        s["name"].casefold(): {c.casefold(): header_unit(c) for c in s["columns"]}
        for s in inputs
    }
    resolved = {}
    resolved_expressions = {}

    def dimension(unit):
        return (
            ("money", SCALES[unit])
            if unit in SCALES
            else (unit, Decimal(1)) if unit else None
        )

    def evaluate(node, scope):
        if node is None or isinstance(node, exp.Null):
            return None
        if isinstance(node, (exp.Alias, exp.Paren, exp.Cast, exp.Window, exp.Neg)):
            return evaluate(node.this, scope)
        if isinstance(node, exp.Subquery):
            values = list(resolved_expressions.get(id(node.this), {}).values())
            return values[0] if len(values) == 1 else None
        if isinstance(node, exp.Column):
            source = scope.sources.get(node.table)
            if isinstance(source, Scope):
                return resolved.get(id(source), {}).get(node.name.casefold())
            if isinstance(source, exp.Table):
                return dimension(
                    sources.get(source.name.casefold(), {}).get(node.name.casefold())
                )
            return None
        if isinstance(node, exp.Literal):
            return ("number", Decimal(1)) if node.is_number else None
        if isinstance(node, exp.Anonymous):
            if node.name.casefold() in {"money_cents", "money_product_cents"}:
                return dimension("分")
            return None
        if isinstance(node, exp.Count):
            return ("number", Decimal(1))
        if isinstance(node, exp.Case):
            branches = [v.args.get("true") for v in node.args.get("ifs", [])]
            branches.append(node.args.get("default"))
            values = [
                evaluate(v, scope)
                for v in branches
                if v is not None
                and not isinstance(v, exp.Null)
                and not (
                    isinstance(v, exp.Literal) and v.is_number and Decimal(v.this) == 0
                )
            ]
            return values[0] if values and all(v == values[0] for v in values) else None
        if isinstance(node, (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Abs, exp.Round)):
            return evaluate(node.this, scope)
        if isinstance(node, exp.Coalesce):
            values = [
                evaluate(n, scope)
                for n in [node.this, *node.expressions]
                if not isinstance(n, exp.Null)
                and not (
                    isinstance(n, exp.Literal) and n.is_number and Decimal(n.this) == 0
                )
            ]
            return values[0] if values and all(v == values[0] for v in values) else None
        if isinstance(node, (exp.Add, exp.Sub)):
            left, right = evaluate(node.this, scope), evaluate(node.expression, scope)
            return left if left == right else None
        if isinstance(node, (exp.Mul, exp.Div)):
            left, right = evaluate(node.this, scope), evaluate(node.expression, scope)
            if (
                left
                and left[0] == "money"
                and isinstance(node.expression, exp.Literal)
                and node.expression.is_number
            ):
                value = Decimal(node.expression.this)
                if value > 0:
                    return (
                        "money",
                        (
                            left[1] * value
                            if isinstance(node, exp.Div)
                            else left[1] / value
                        ),
                    )
            if (
                isinstance(node, exp.Div)
                and left
                and left == right
                and left[0] == "money"
            ):
                return ("number", Decimal(1))
            if left == right == ("number", Decimal(1)):
                return left
        return None

    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
        # Ordering cannot change a projected value's dimension. SQLite rowid
        # need not be a declared column, so exclude select-order clauses from
        # unit analysis instead of letting an irrelevant ORDER BY erase units.
        for select in tree.find_all(exp.Select):
            select.set("order", None)
        tree = qualify(
            tree,
            schema=schema,
            dialect="sqlite",
            validate_qualify_columns=False,
        )
        scopes = list(traverse_scope(tree))
        for scope in scopes:
            if isinstance(scope.expression, exp.SetOperation):
                branches = [
                    resolved.get(id(child), {}) for child in scope.set_operation_scopes
                ]
                outputs = scope.expression.named_selects
                values = list(branches[0].values()) if branches else []
                resolved[id(scope)] = {
                    name.casefold(): (
                        values[i]
                        if i < len(values)
                        and all(
                            i < len(b) and list(b.values())[i] == values[i]
                            for b in branches
                        )
                        else None
                    )
                    for i, name in enumerate(outputs)
                }
            else:
                resolved[id(scope)] = {
                    n.alias_or_name.casefold(): evaluate(n, scope)
                    for n in scope.expression.selects
                }
            resolved_expressions[id(scope.expression)] = resolved[id(scope)]
        values = list(resolved.get(id(scopes[-1]), {}).values()) if scopes else []
        result = {}
        for i, name in enumerate(output_columns):
            value = values[i] if i < len(values) else None
            result[name] = (
                next((k for k, scale in SCALES.items() if scale == value[1]), None)
                if value and value[0] == "money"
                else value[0] if value else None
            )
        return result
    except (
        sqlglot.errors.SqlglotError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        ArithmeticError,
    ):
        return unknown
