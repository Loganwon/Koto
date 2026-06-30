# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import re as _re_fn
import unicodedata

from werkzeug.utils import secure_filename as _werkzeug_secure_filename


def secure_filename(name: str) -> str:
    if not name:
        return ""
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\x00", "").replace("/", "_").replace("\\", "_")
    name = name.replace(":", "_").replace("*", "_").replace("?", "_")
    name = name.replace('"', "_").replace("<", "_").replace(">", "_").replace("|", "_")
    name = _re_fn.sub(r"[\s_]+", "_", name)
    name = name.strip(". _")
    base, _, _ext = name.rpartition(".")
    if not base.strip(". _"):
        fallback = _werkzeug_secure_filename(name)
        return fallback if fallback else ""
    return name
