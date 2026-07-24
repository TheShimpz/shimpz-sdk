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

    accounts: tuple[str, ...]


def power(*, accounts: Iterable[str] = ()) -> Callable[[PowerBody], PowerBody]:
    """Declare an async ``run`` function as the Power in its Python file."""
    account_ids = _validate_accounts(accounts)

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
        setattr(body, _METADATA_ATTRIBUTE, PowerMetadata(accounts=account_ids))
        return body

    return decorate


def get_power_metadata(body: object) -> PowerMetadata | None:
    """Return declaration metadata without maintaining a global registry."""
    metadata = getattr(body, _METADATA_ATTRIBUTE, None)
    return metadata if isinstance(metadata, PowerMetadata) else None


def _validate_accounts(accounts: Iterable[str]) -> tuple[str, ...]:
    if isinstance(accounts, str):
        message = "accounts must be an iterable of account ids"
        raise TypeError(message)
    account_ids = tuple(accounts)
    if len(account_ids) != len(set(account_ids)):
        message = "Power accounts must be unique"
        raise ValueError(message)
    if not all(_valid_id(account_id) for account_id in account_ids):
        message = "Power account id is invalid"
        raise ValueError(message)
    return account_ids


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
