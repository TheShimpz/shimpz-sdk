"""Declare how a mutating Action's provider honors the logical operation id as an idempotency key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._protocol.action_effect import (
    KEY_LOCATIONS,
    KEY_NAME,
    KEY_SCOPES,
    MAX_PROVIDER_HOST,
    MAX_RETENTION_SECONDS,
    MIN_RETENTION_SECONDS,
    PROVIDER_HOST,
)


@dataclass(frozen=True, slots=True)
class Idempotency:
    """The provider's documented idempotency for the key an Action sends from ``ctx.operation_id``.

    ``provider`` is one of the manifest's allowed hosts, ``key_location`` and ``key_name`` say where it reads the key,
    ``scope`` is ``"account"`` or ``"endpoint"``, ``retention_seconds`` is how long it remembers a key, and
    ``same_payload_required`` says whether a reused key must carry an identical payload. Without this declaration
    Team relies on no provider idempotency.
    """

    provider: str
    key_location: Literal["header", "query", "body"]
    key_name: str
    scope: Literal["account", "endpoint"]
    retention_seconds: int
    same_payload_required: bool

    def __post_init__(self) -> None:
        if not (
            isinstance(self.provider, str)
            and len(self.provider) <= MAX_PROVIDER_HOST
            and PROVIDER_HOST.fullmatch(self.provider) is not None
            and self.key_location in KEY_LOCATIONS
            and isinstance(self.key_name, str)
            and KEY_NAME.fullmatch(self.key_name) is not None
            and self.scope in KEY_SCOPES
            and type(self.retention_seconds) is int
            and MIN_RETENTION_SECONDS <= self.retention_seconds <= MAX_RETENTION_SECONDS
            and type(self.same_payload_required) is bool
        ):
            raise ValueError("Idempotency declaration is invalid")

    def contract(self) -> dict[str, object]:
        """Return the closed machine-contract idempotency declaration."""
        return {
            "provider": self.provider,
            "key": {"location": self.key_location, "name": self.key_name},
            "scope": self.scope,
            "retention_seconds": self.retention_seconds,
            "same_payload_required": self.same_payload_required,
        }
