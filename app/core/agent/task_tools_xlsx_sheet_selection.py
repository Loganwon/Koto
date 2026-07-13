"""Workbook sheet selection and financial-statement recognition helpers."""

from __future__ import annotations

import re
from typing import Any


GENERIC_SHEET_NAME_GUESSES = {"sheet", "sheet1", "工作表", "工作表1"}
FINANCIAL_STATEMENT_PATTERNS = {
    "profit_and_loss": (
        re.compile(r"(?:^|\b)(p\s*&\s*l|profit\s*&?\s*loss|income\s*statement)(?:\b|$)", re.IGNORECASE),
        re.compile(r"利润|损益|收入成本", re.IGNORECASE),
    ),
    "balance_sheet": (
        re.compile(r"(?:^|\b)(balance\s*sheet|statement\s*of\s*financial\s*position|bs)(?:\b|$)", re.IGNORECASE),
        re.compile(r"资产负债", re.IGNORECASE),
    ),
    "cash_flow": (
        re.compile(r"(?:^|\b)(cash\s*flow|cashflow|cf)(?:\b|$)", re.IGNORECASE),
        re.compile(r"现金流", re.IGNORECASE),
    ),
}


def select_workbook_sheet(workbook: Any, requested_sheet: Any = "") -> tuple[str, str, str]:
    sheetnames = list(getattr(workbook, "sheetnames", []) or [])
    requested = str(requested_sheet or "").strip()
    if not sheetnames:
        return "", requested, "Workbook has no sheets"
    if not requested:
        return sheetnames[0], requested, ""
    if requested in sheetnames:
        return requested, requested, ""
    if len(sheetnames) == 1 or requested.casefold() in GENERIC_SHEET_NAME_GUESSES:
        fallback = sheetnames[0]
        return fallback, requested, f"Sheet '{requested}' not found; used '{fallback}' instead."
    return "", requested, f"Sheet '{requested}' not found. Available: {sheetnames}"


def sheet_matches_statement(sheet_name: Any, statement_key: str) -> bool:
    name = str(sheet_name or "").strip()
    return bool(name and any(pattern.search(name) for pattern in FINANCIAL_STATEMENT_PATTERNS.get(statement_key, ())))
