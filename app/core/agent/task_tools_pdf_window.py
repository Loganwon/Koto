"""Bounded PDF extraction and letter-window discovery for file task tools."""

from __future__ import annotations

import re
from typing import Any, Callable

PDF_ROMAN_DIGITS = ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
PDF_CHINESE_DIGITS = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
}


def read_pdf_excerpt(
    path: str,
    *,
    max_chars: int,
    start_page: int = 1,
    end_page: int = 0,
    allow_full_fallback: bool = True,
    logger: Any,
) -> str:
    """Read a bounded PDF window, falling back only when explicitly allowed."""
    start_page = max(1, int(start_page or 1))
    end_page = max(0, int(end_page or 0))

    def collect_pdfplumber() -> str:
        import pdfplumber  # type: ignore

        parts: list[str] = []
        total = 0
        with pdfplumber.open(path) as pdf:
            last_page = min(end_page or len(pdf.pages), len(pdf.pages))
            for index in range(start_page - 1, last_page):
                try:
                    page_text = pdf.pages[index].extract_text() or ""
                except Exception as exc:
                    logger.debug(
                        "[TaskTools] pdfplumber page %s failed: %s", index + 1, exc
                    )
                    page_text = ""
                if page_text.strip():
                    block = f"[Page {index + 1}]\n{page_text.strip()}"
                    parts.append(block)
                    total += len(block)
                    if total >= max_chars:
                        break
        return "\n\n".join(parts)

    def collect_pypdf() -> str:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(path)
        parts: list[str] = []
        total = 0
        last_page = min(end_page or len(reader.pages), len(reader.pages))
        for index in range(start_page - 1, last_page):
            try:
                page_text = reader.pages[index].extract_text() or ""
            except Exception as exc:
                logger.debug("[TaskTools] pypdf page %s failed: %s", index + 1, exc)
                page_text = ""
            if page_text.strip():
                block = f"[Page {index + 1}]\n{page_text.strip()}"
                parts.append(block)
                total += len(block)
                if total >= max_chars:
                    break
        return "\n\n".join(parts)

    for collector in (collect_pdfplumber, collect_pypdf):
        try:
            excerpt = collector()
            if excerpt.strip():
                return excerpt[:max_chars]
        except ImportError:
            continue
        except Exception as exc:
            logger.debug("[TaskTools] PDF excerpt collector failed: %s", exc)
    if not allow_full_fallback:
        return ""
    from app.core.workflow_engine import parse_source_file

    return parse_source_file(path)[:max_chars]


def int_to_pdf_roman(value: int) -> str:
    number = max(1, int(value or 1))
    output: list[str] = []
    for unit, symbol in PDF_ROMAN_DIGITS:
        while number >= unit:
            output.append(symbol)
            number -= unit
    return "".join(output)


def int_to_chinese_letter_number(value: int) -> str:
    number = max(1, int(value or 1))
    if number < 10:
        return PDF_CHINESE_DIGITS.get(number, "")
    if number == 10:
        return "十"
    if number < 20:
        return "十" + PDF_CHINESE_DIGITS.get(number - 10, "")
    tens, ones = divmod(number, 10)
    return (
        PDF_CHINESE_DIGITS.get(tens, "")
        + "十"
        + (PDF_CHINESE_DIGITS.get(ones, "") if ones else "")
    )


def pdf_letter_heading_terms(value: int) -> list[str]:
    chinese = int_to_chinese_letter_number(value)
    roman = int_to_pdf_roman(value)
    return [
        f"第{chinese}封信",
        f"第 {chinese} 封信",
        f"Letter {roman}",
        f"LETTER {roman}",
        f"letter {roman.lower()}",
    ]


def pdf_page_has_letter_heading(page_text: str, terms: list[str]) -> bool:
    text = str(page_text or "")
    if ("目 录" in text or "目录" in text) and len(
        re.findall(r"第[一二三四五六七八九十]+封信", text)
    ) >= 5:
        return False
    normalized_terms = {re.sub(r"\s+", "", term).lower() for term in terms}
    return any(
        re.sub(r"\s+", "", line).strip().lower() in normalized_terms
        for line in text.splitlines()
    )


def read_pdf_letter_window(
    path: str,
    *,
    max_chars: int,
    start_letter: int,
    end_letter: int,
    read_excerpt: Callable[..., str],
) -> str:
    start_letter = max(1, int(start_letter or 1))
    end_letter = max(start_letter, int(end_letter or start_letter))
    start_terms = pdf_letter_heading_terms(start_letter)
    next_terms = pdf_letter_heading_terms(end_letter + 1)
    found_start_page = 0
    found_end_page = 0
    for page in range(1, 400):
        page_text = read_excerpt(
            path,
            max_chars=240_000,
            start_page=page,
            end_page=page,
            allow_full_fallback=False,
        )
        if not page_text.strip():
            if found_start_page and page > found_start_page + 30:
                break
            continue
        if not found_start_page and pdf_page_has_letter_heading(page_text, start_terms):
            found_start_page = page
        elif (
            found_start_page
            and page > found_start_page
            and pdf_page_has_letter_heading(page_text, next_terms)
        ):
            found_end_page = page - 1
            break
    if not found_start_page:
        return ""
    found_end_page = found_end_page or min(found_start_page + 30, 399)
    header = (
        f"[PDF letter window: {start_letter}-{end_letter}; "
        f"resolved pages {found_start_page}-{found_end_page}]\n"
    )
    body = read_excerpt(
        path,
        max_chars=max(1, max_chars - len(header)),
        start_page=found_start_page,
        end_page=found_end_page,
    )
    return (header + body).strip()[:max_chars]
