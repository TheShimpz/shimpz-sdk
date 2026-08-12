"""Declare one file-backed Assistant Action."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

_METADATA_ATTRIBUTE = "__shimpz_action__"

Params = ParamSpec("Params")
Result = TypeVar("Result")
ActionBody = Callable[Params, Awaitable[Result]]


@dataclass(frozen=True, slots=True)
class ActionMetadata:
    """Immutable author intent attached to an Action body."""

    integrations: tuple[str, ...]
    human_requests: tuple[str, ...]


def action(
    *,
    integrations: Iterable[str] = (),
    human_requests: Iterable[str] = (),
) -> Callable[[ActionBody], ActionBody]:
    """Declare an async ``run`` function as the Action in its Python file."""
    integration_ids = _validate_integrations(integrations)
    request_capabilities = _validate_human_requests(human_requests)

    def decorate(body: ActionBody) -> ActionBody:
        if body.__name__ != "run":
            message = "an Action function must be named run"
            raise ValueError(message)
        if not inspect.iscoroutinefunction(body):
            message = "an Action function must be async"
            raise TypeError(message)
        if hasattr(body, _METADATA_ATTRIBUTE):
            message = "an Action function can only be declared once"
            raise ValueError(message)
        setattr(
            body,
            _METADATA_ATTRIBUTE,
            ActionMetadata(
                integrations=integration_ids,
                human_requests=request_capabilities,
            ),
        )
        return body

    return decorate


def get_action_metadata(body: object) -> ActionMetadata | None:
    """Return declaration metadata without maintaining a global registry."""
    metadata = getattr(body, _METADATA_ATTRIBUTE, None)
    return metadata if isinstance(metadata, ActionMetadata) else None


def _validate_integrations(integrations: Iterable[str]) -> tuple[str, ...]:
    if isinstance(integrations, str):
        message = "integrations must be an iterable of integration ids"
        raise TypeError(message)
    integration_ids = tuple(integrations)
    if len(integration_ids) != len(set(integration_ids)):
        message = "Action integrations must be unique"
        raise ValueError(message)
    if not all(_valid_id(integration_id) for integration_id in integration_ids):
        message = "Action integration id is invalid"
        raise ValueError(message)
    return integration_ids


def _validate_human_requests(human_requests: Iterable[str]) -> tuple[str, ...]:
    if isinstance(human_requests, str):
        message = "human_requests must be an iterable of capability ids"
        raise TypeError(message)
    capabilities = tuple(human_requests)
    supported = {
        "approval",
        "input:text",
        "input:textarea",
        "input:password",
        "input:phone",
        "input:select",
        "input:choice",
        "input:choices",
        "auth:reauth",
        "auth:second-factor",
        "auth:phishing-resistant",
    }
    if len(capabilities) != len(set(capabilities)) or any(item not in supported for item in capabilities):
        message = "Action human request capability is invalid"
        raise ValueError(message)
    return tuple(sorted(capabilities))


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
