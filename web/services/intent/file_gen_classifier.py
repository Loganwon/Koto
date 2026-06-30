# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary


def is_explicit_file_gen_request(requirement: str) -> bool:
    from web.file_generation import _is_explicit_file_gen_request as _impl
    return _impl(requirement)
