# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Lazy adapter for legacy web PPT implementations."""

from __future__ import annotations


def load_planner_cls():
    from web.ppt_master import PPTContentPlanner

    return PPTContentPlanner


def load_generator_cls():
    from web.ppt_generator import PPTGenerator

    return PPTGenerator


__all__ = ["load_generator_cls", "load_planner_cls"]
