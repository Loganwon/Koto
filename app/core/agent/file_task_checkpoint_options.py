# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from typing import Any, Dict, Mapping


def workflow_checkpoint_from_options(options: Mapping[str, Any]) -> Dict[str, Any]:
    checkpoint = options.get("workflow_checkpoint")
    if isinstance(checkpoint, Mapping):
        return dict(checkpoint)

    return {}
