"""Declare how Team verifies whether a mutating Action's uncertain effect occurred."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from ._protocol.action_effect_validator import MAX_BINDING_NAME, MAX_BINDINGS, pointer_tokens
from ._request import valid_id

Effect = Literal["read_only", "mutating"]
# Annotate a verifier's outcome field with exactly these three states.
VerificationOutcome = Literal["occurred", "not_occurred", "inconclusive"]


@dataclass(frozen=True, slots=True)
class Binding:
    """One fixed verifier input source: an original input value or the original ``operation_id``."""

    source: Literal["input", "operation_id"]
    pointer: str | None = None

    def __post_init__(self) -> None:
        if self.source == "operation_id" and self.pointer is None:
            return
        if self.source != "input" or pointer_tokens(self.pointer) is None:
            raise ValueError("Verifier binding is invalid")

    def contract(self) -> dict[str, str]:
        """Return the closed machine-contract binding."""
        if self.pointer is None:
            return {"from": "operation_id"}
        return {"from": "input", "pointer": self.pointer}


def from_input(pointer: str) -> Binding:
    """Bind one value of the original Action input, addressed by an RFC 6901 pointer such as ``/zone``."""
    return Binding("input", pointer)


def from_operation_id() -> Binding:
    """Bind the original logical operation's ``operation_id``; the verifier property must be a plain ``str``."""
    return Binding("operation_id")


@dataclass(frozen=True, slots=True)
class Verifier:
    """A read-only Action of the same Assistant that reports whether this Action's effect occurred.

    ``outcome`` points to a required ``VerificationOutcome`` field of the verifier's result, and ``result`` points
    to the recovered result, whose type must be exactly this Action's return type.
    """

    action: str
    inputs: Mapping[str, Binding]
    outcome: str
    result: str

    def __post_init__(self) -> None:
        if not isinstance(self.inputs, Mapping):
            raise TypeError("Verifier inputs must map verifier input names to bindings")
        inputs = dict(self.inputs)
        if (
            not valid_id(self.action)
            or not 1 <= len(inputs) <= MAX_BINDINGS
            or any(not isinstance(name, str) or not 1 <= len(name) <= MAX_BINDING_NAME for name in inputs)
            or any(not isinstance(binding, Binding) for binding in inputs.values())
            or pointer_tokens(self.outcome) is None
            or pointer_tokens(self.result) is None
        ):
            raise ValueError("Verifier declaration is invalid")
        object.__setattr__(self, "inputs", MappingProxyType(inputs))

    def contract(self) -> dict[str, object]:
        """Return the closed machine-contract verifier descriptor."""
        return {
            "action": self.action,
            "input": {name: binding.contract() for name, binding in self.inputs.items()},
            "outcome": self.outcome,
            "result": self.result,
        }
