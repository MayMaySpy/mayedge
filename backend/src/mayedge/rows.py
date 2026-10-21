"""Type guards for rows that arrive as JSON: venue answers, stored runs, ticket bodies.

They check exactly what isinstance checks, and tell the type checker the keys are
strings, so a field read is Any rather than unknown.
"""

from __future__ import annotations

from typing import Any, TypeGuard


def is_obj(raw: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(raw, dict)


def is_list(raw: object) -> TypeGuard[list[Any]]:
    return isinstance(raw, list)


def obj(raw: object) -> dict[str, Any]:
    """The row itself when it is an object, else an empty one."""
    return raw if is_obj(raw) else {}


def items(raw: object) -> list[Any]:
    """The row itself when it is a list, else an empty one."""
    return raw if is_list(raw) else []
