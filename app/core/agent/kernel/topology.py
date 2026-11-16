from __future__ import annotations

from typing import Dict, Tuple

_NODES: Tuple[Tuple[str, str], ...] = (
    ("request", "Agent request"),
    ("prepare", "Context + fixed tool profile"),
    ("model", "Model gateway"),
    ("guard", "RunGuard budgets"),
    ("tools", "Tool catalog + policy"),
    ("execute", "Tool executor"),
    ("validate", "Output verification"),
    ("complete", "Agent result + events"),
)

_EDGES: Tuple[Tuple[str, str, str], ...] = (
    ("request", "prepare", "normalize"),
    ("prepare", "model", "messages + allowlist"),
    ("guard", "model", "step budget"),
    ("model", "tools", "tool calls"),
    ("tools", "execute", "allowed"),
    ("execute", "model", "structured result"),
    ("model", "validate", "final answer"),
    ("validate", "model", "one repair"),
    ("validate", "complete", "verified"),
)


def runtime_topology() -> Dict[str, list[dict[str, str]]]:
    """Return the provider-neutral runtime topology for diagnostics and UI."""
    return {
        "nodes": [{"id": node_id, "label": label} for node_id, label in _NODES],
        "edges": [
            {"source": source, "target": target, "label": label}
            for source, target, label in _EDGES
        ],
    }


def runtime_mermaid() -> str:
    """Render the canonical Kernel runtime topology as Mermaid markup."""
    lines = ["flowchart LR"]
    for node_id, label in _NODES:
        lines.append(f'    {node_id}["{label}"]')
    for source, target, label in _EDGES:
        lines.append(f'    {source} -->|"{label}"| {target}')
    return "\n".join(lines)


__all__ = ["runtime_mermaid", "runtime_topology"]
