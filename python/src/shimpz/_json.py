"""Strict JSON decoding for public and private SDK boundaries."""

import json
from typing import Any


def strict_loads(text: str) -> object:
    """Decode JSON while rejecting duplicate keys and non-finite constants."""
    return json.loads(
        text,
        parse_constant=_reject_constant,
        object_pairs_hook=_unique_object,
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")
