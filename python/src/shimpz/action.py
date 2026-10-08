"""Declare one file-backed Assistant Action."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

from .effect import Mutating
from .idempotency import Idempotency
from .verifier import Effect, Verifier

_METADATA_ATTRIBUTE = "__shimpz_action__"
_AUTHORIZATION_REQUESTS = {"approval", "auth:password", "auth:totp", "auth:passkey"}
# The most Stored Inputs one Action may use: every one its manifest can declare.
_MAX_ACTION_STORED_INPUTS = 8

Params = ParamSpec("Params")
Result = TypeVar("Result")
ActionBody = Callable[Params, Awaitable[Result]]


@dataclass(frozen=True, slots=True)
class ActionMetadata:
    """Immutable author intent attached to an Action body."""

    integrations: tuple[str, ...]
    stored_inputs: tuple[str, ...]
    human_requests: tuple[str, ...]
    effect: Effect = "mutating"
    verifier: Verifier | None = None
    idempotency: Idempotency | None = None


def action(
    *,
    integrations: Iterable[str] = (),
    stored_inputs: Iterable[str] = (),
    human_requests: Iterable[str] = (),
    effect: Effect | Mutating = "mutating",
) -> Callable[[ActionBody], ActionBody]:
    """Declare an async ``run`` function as the Action in its Python file.

    ``effect`` is ``"mutating"`` unless the Action is declared ``"read_only"``: it then must have no business side
    effect such as publishing, deleting, or delivering a message. ``Mutating(verifier=..., idempotency=...)`` declares
    a mutating Action together with how Team may verify it and how its provider deduplicates it.
    """
    integration_ids = _validate_integrations(integrations)
    stored_input_ids = _validate_stored_inputs(stored_inputs)
    request_capabilities = _validate_human_requests(human_requests)
    if stored_input_ids and "input:password" not in request_capabilities:
        message = "Action Stored Input requires input:password"
        raise ValueError(message)
    if not isinstance(effect, Mutating) and effect not in ("read_only", "mutating"):
        message = "Action effect must be read_only, mutating, or shimpz.Mutating"
        raise ValueError(message)
    declared = effect if isinstance(effect, Mutating) else Mutating()

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
                stored_inputs=stored_input_ids,
                human_requests=request_capabilities,
                effect="read_only" if effect == "read_only" else "mutating",
                verifier=declared.verifier,
                idempotency=declared.idempotency,
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
        "auth:password",
        "auth:totp",
        "auth:passkey",
    }
    if len(capabilities) != len(set(capabilities)) or any(item not in supported for item in capabilities):
        message = "Action human request capability is invalid"
        raise ValueError(message)
    if sum(item in _AUTHORIZATION_REQUESTS for item in capabilities) > 1:
        message = "Action must declare at most one authorization request"
        raise ValueError(message)
    return tuple(sorted(capabilities))


def _validate_stored_inputs(stored_inputs: Iterable[str]) -> tuple[str, ...]:
    if isinstance(stored_inputs, str):
        message = "stored_inputs must be an iterable of Stored Input ids"
        raise TypeError(message)
    stored_input_ids = tuple(stored_inputs)
    if (
        len(stored_input_ids) > _MAX_ACTION_STORED_INPUTS
        or len(stored_input_ids) != len(set(stored_input_ids))
        or not all(_valid_id(stored_input_id) for stored_input_id in stored_input_ids)
    ):
        message = "Action Stored Input declaration is invalid"
        raise ValueError(message)
    return tuple(sorted(stored_input_ids))


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
        and "--" not in value
    )
