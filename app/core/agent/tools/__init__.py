"""Domain-organized implementations for the canonical Agent tool catalog.

This package only exposes tool functions. Registration and metadata are owned by
``app.core.agent.tool_registry.ToolRegistry`` and the Kernel ``ToolCatalog``.
"""

from __future__ import annotations

# File comparison
from app.core.agent.toolkits.foundation.multi_file import (  # noqa: F401, E402
    compare_files,
)

from . import _internal  # noqa: F401, E402  provides internal helpers for all modules

# File conversion
from .conversion import convert_file, list_conversions  # noqa: F401, E402

# DOCX annotation
from .docx_annotate import (  # noqa: F401, E402
    clear_docx_review_marks,
    compare_docx_and_annotate,
    plan_docx_compare_annotations,
    write_docx_comments,
)

# DOCX composite
from .docx_composite import (  # noqa: F401, E402
    insert_docx_paragraph,
    insert_excel_as_docx_table,
    insert_image_into_docx,
)

# DOCX conversion
from .docx_convert import convert_docx_to_pdf  # noqa: F401, E402

# DOCX read
from .docx_read import read_docx_content  # noqa: F401, E402

# DOCX template
from .docx_template import fill_docx_template  # noqa: F401, E402

# DOCX write
from .docx_write import write_docx_content  # noqa: F401, E402

# Filesystem tools
from .filesystem import (  # noqa: F401, E402
    copy_file,
    create_file,
    list_workspace_files,
    open_file_in_editor,
)

# PPTX
from .pptx import (  # noqa: F401, E402
    add_pptx_slides,
    design_pptx_theme_layout,
    write_pptx_slides,
)

# Sandbox execution
from .sandbox import SandboxRunResult, run_python_in_sandbox  # noqa: F401, E402

# Text file tools
from .text import (  # noqa: F401, E402
    parse_file_to_text,
    read_file_range,
    replace_file_selection,
)

# XLSX read
from .xlsx_read import _read_xlsx_sheet_window  # noqa: F401, E402

# ---------------------------------------------------------------------------
# Re-export all public tool functions from domain modules
# ---------------------------------------------------------------------------
