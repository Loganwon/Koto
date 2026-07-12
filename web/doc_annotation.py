"""Compatibility adapter for the migrated document annotation decision."""

from app.core.routing.rule_router import RuleRouter


def _resolve_annotation_system(requirement: str, has_file: bool = False) -> bool:
    return RuleRouter.should_use_annotation_system(requirement, has_file=has_file)
