"""Deterministic visible-text counts supplied to the semantic write verifier."""


def characters(text):
    return len(str(text).replace("\r", "").replace("\n", ""))


def proposed_metrics(tool, args):
    if tool == "create_word":
        sections = args.get("sections", [])
        paragraphs = sum(characters(s.get("text", "")) for s in sections)
        headings = sum(characters(s.get("heading", "")) for s in sections)
        tables = sum(
            characters(v)
            for table in args.get("tables", [])
            for row in table
            for v in row
        )
        return {
            "counting": "Unicode characters, excluding line breaks and document title",
            "paragraph_characters": paragraphs,
            "body_characters_including_headings_and_tables": paragraphs
            + headings
            + tables,
        }
    if tool == "create_presentation":
        return {
            "counting": "Unicode characters, excluding line breaks and slide titles",
            "slide_count": len(args.get("sections", [])),
            "slide_body_characters": [
                characters(s.get("text", "")) for s in args.get("sections", [])
            ],
        }
    return {}


def artifact_metrics(path):
    if path.suffix.lower() == ".docx":
        from docx import Document

        return document_metrics(Document(path))
    if path.suffix.lower() == ".pptx":
        from pptx import Presentation

        return presentation_metrics(Presentation(path))
    return {}


def document_metrics(document):
    paragraphs = [
        p for p in document.paragraphs if p.style.name not in ("Title", "Subtitle")
    ]
    return {
        "counting": "Unicode characters excluding line breaks and document title",
        "paragraph_characters": sum(
            characters(p.text)
            for p in paragraphs
            if not p.style.name.startswith("Heading")
        ),
        "body_characters_including_headings_and_tables": sum(
            characters(p.text) for p in paragraphs
        )
        + sum(
            characters(c.text) for t in document.tables for r in t.rows for c in r.cells
        ),
    }


def presentation_metrics(presentation):
    return {
        "counting": "Unicode characters excluding line breaks and slide titles",
        "slide_count": len(presentation.slides),
        "slide_body_characters": [
            sum(
                characters(sh.text)
                for sh in slide.shapes
                if sh.has_text_frame and sh != slide.shapes.title
            )
            for slide in presentation.slides
        ],
    }
