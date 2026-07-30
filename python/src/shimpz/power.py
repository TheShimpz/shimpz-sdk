"""Declare one file-backed Assistant Power."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

_METADATA_ATTRIBUTE = "__shimpz_power__"

Params = ParamSpec("Params")
Result = TypeVar("Result")
PowerBody = Callable[Params, Awaitable[Result]]


@dataclass(frozen=True, slots=True)
class PowerMetadata:
    """Immutable author intent attached to a Power body."""

    integrations: tuple[str, ...]


def power(*, integrations: Iterable[str] = ()) -> Callable[[PowerBody], PowerBody]:
    """Declare an async ``run`` function as the Power in its Python file."""
    integration_ids = _validate_integrations(integrations)

    def decorate(body: PowerBody) -> PowerBody:
        if body.__name__ != "run":
            message = "a Power function must be named run"
            raise ValueError(message)
        if not inspect.iscoroutinefunction(body):
            message = "a Power function must be async"
            raise TypeError(message)
        if hasattr(body, _METADATA_ATTRIBUTE):
            message = "a Power function can only be declared once"
            raise ValueError(message)
        setattr(body, _METADATA_ATTRIBUTE, PowerMetadata(integrations=integration_ids))
        return body

    return decorate


def get_power_metadata(body: object) -> PowerMetadata | None:
    """Return declaration metadata without maintaining a global registry."""
    metadata = getattr(body, _METADATA_ATTRIBUTE, None)
    return metadata if isinstance(metadata, PowerMetadata) else None


def _validate_integrations(integrations: Iterable[str]) -> tuple[str, ...]:
    if isinstance(integrations, str):
        message = "integrations must be an iterable of integration ids"
        raise TypeError(message)
    integration_ids = tuple(integrations)
    if len(integration_ids) != len(set(integration_ids)):
        message = "Power integrations must be unique"
        raise ValueError(message)
    if not all(_valid_id(integration_id) for integration_id in integration_ids):
        message = "Power integration id is invalid"
        raise ValueError(message)
    return integration_ids


def _valid_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value[0].isascii()
        and value[0].islower()
        and all(
            character.isascii() and (character.islower() or character.isdigit() or character == "-")
            for character in value
        )
        and not value.endswith("-")
    )
