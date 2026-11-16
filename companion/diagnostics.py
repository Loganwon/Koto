"""Unexpected-error locations without credentials, request bodies or document text."""

import json
import logging
from pathlib import Path
import traceback
import uuid


def record_error(error):
    previous = getattr(error, "_koto_diagnostic", None)
    if previous:
        return previous
    identity = uuid.uuid4().hex[:12]
    frames = [
        {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
        for f in traceback.extract_tb(error.__traceback__)[-12:]
    ]
    logging.getLogger("companion.diagnostics").error(
        json.dumps(
            {
                "diagnostic_id": identity,
                "type": type(error).__name__,
                "frames": frames,
            },
            ensure_ascii=False,
        )
    )
    try:
        error._koto_diagnostic = identity
    except (AttributeError, TypeError):
        pass
    return identity
