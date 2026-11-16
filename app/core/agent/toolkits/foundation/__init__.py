"""Koto's built-in office and file-processing toolkit.

The package is the stable ownership boundary for general-purpose capabilities
that ship with Koto. Format modules remain internal implementation units; the
Kernel sees one versioned toolkit source rather than unrelated plugins.
"""

from app.core.agent.kernel import KERNEL_API_VERSION
from app.core.agent.toolkits.contracts import ToolkitDescriptor
from app.core.agent.toolkits.foundation.capabilities import (
    FOUNDATION_CAPABILITY_IDS,
    CapabilityMaturity,
    FoundationCapability,
    foundation_capabilities,
    foundation_capability_report,
    validate_foundation_capabilities,
)

FOUNDATION_TOOLKIT = ToolkitDescriptor(
    toolkit_id="koto.foundation",
    version="1.0.0",
    api_version=KERNEL_API_VERSION,
    description="Built-in document, spreadsheet, presentation, file, and sandbox tools.",
    capabilities=FOUNDATION_CAPABILITY_IDS,
)

FOUNDATION_TOOLKIT_ID = FOUNDATION_TOOLKIT.toolkit_id
FOUNDATION_TOOLKIT_VERSION = FOUNDATION_TOOLKIT.version
FOUNDATION_TOOL_SOURCE = FOUNDATION_TOOLKIT.source

__all__ = [
    "FOUNDATION_TOOLKIT",
    "FOUNDATION_TOOLKIT_ID",
    "FOUNDATION_TOOLKIT_VERSION",
    "FOUNDATION_TOOL_SOURCE",
    "FOUNDATION_CAPABILITY_IDS",
    "CapabilityMaturity",
    "FoundationCapability",
    "foundation_capabilities",
    "foundation_capability_report",
    "validate_foundation_capabilities",
]
