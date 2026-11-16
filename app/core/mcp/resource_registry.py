# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""MCP Resource Registry — register and serve MCP resources."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from app.core.mcp.protocol import MCPResource

logger = logging.getLogger(__name__)


class MCPResourceRegistry:
    """Registry for MCP resources (static and templated).

    Resources are URI-addressable data sources that MCP clients can read.
    Resource templates allow parameterized URIs (e.g. file://{path}).
    """

    def __init__(self):
        self._resources: Dict[str, MCPResource] = {}
        self._templates: Dict[str, Dict[str, Any]] = {}

    # ── Registration ────────────────────────────────────────────────────────

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str = "",
        mime_type: Optional[str] = None,
        handler: Optional[Callable[[], str]] = None,
    ) -> MCPResource:
        """Register a static resource."""
        if uri in self._resources:
            raise ValueError(f"Resource URI {uri!r} already registered")

        resource = MCPResource(
            uri=uri,
            name=name,
            description=description,
            mimeType=mime_type,
            handler=handler,
        )
        self._resources[uri] = resource
        logger.debug("[MCPResourceRegistry] registered resource: %s", uri)
        return resource

    def register_template(
        self,
        uri_template: str,
        name: str,
        description: str = "",
        mime_type: Optional[str] = None,
    ) -> None:
        """Register a resource template."""
        self._templates[uri_template] = {
            "uriTemplate": uri_template,
            "name": name,
            "description": description,
            **({"mimeType": mime_type} if mime_type else {}),
        }

    def unregister_resource(self, uri: str) -> None:
        """Remove a resource by URI."""
        self._resources.pop(uri, None)

    # ── Query ───────────────────────────────────────────────────────────────

    def get(self, uri: str) -> Optional[MCPResource]:
        """Get a resource by exact URI."""
        return self._resources.get(uri)

    def list_resources(self) -> List[Dict[str, Any]]:
        """List all registered resources in MCP format."""
        return [r.to_resource_def() for r in self._resources.values()]

    def list_templates(self) -> List[Dict[str, Any]]:
        """List all registered resource templates."""
        return list(self._templates.values())

    def resource_count(self) -> int:
        return len(self._resources)

    # ── Execution ───────────────────────────────────────────────────────────

    def read_resource(self, uri: str) -> str:
        """Read a resource by URI."""
        resource = self._resources.get(uri)
        if resource is None:
            raise KeyError(f"Resource {uri!r} not found")
        return resource.read()

    # ── Diagnostics ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "resource_count": len(self._resources),
            "template_count": len(self._templates),
            "resources": sorted(self._resources.keys()),
            "templates": sorted(self._templates.keys()),
        }


__all__ = ["MCPResourceRegistry"]
