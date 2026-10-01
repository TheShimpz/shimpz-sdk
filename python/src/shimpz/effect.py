"""Declare what a mutating Action's effect needs for safe recovery."""

from __future__ import annotations

from dataclasses import dataclass

from .idempotency import Idempotency
from .verifier import Verifier


@dataclass(frozen=True, slots=True)
class Mutating:
    """A mutating effect with its optional ``verifier`` and provider ``idempotency``.

    Pass it as ``@action(effect=Mutating(...))``; the plain string ``"mutating"`` declares neither.
    """

    verifier: Verifier | None = None
    idempotency: Idempotency | None = None

    def __post_init__(self) -> None:
        if self.verifier is not None and not isinstance(self.verifier, Verifier):
            raise TypeError("Mutating verifier must be a shimpz.Verifier")
        if self.idempotency is not None and not isinstance(self.idempotency, Idempotency):
            raise TypeError("Mutating idempotency must be a shimpz.Idempotency")
