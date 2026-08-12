"""Public value objects for one Action human request."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

InputKind = Literal["text", "textarea", "password", "phone", "select", "choice", "choices"]


@dataclass(frozen=True, slots=True)
class InputOption:
    """One closed option displayed by a select, choice, or choices request."""

    value: str
    label: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class InputRequest:
    """One specialized input prompt declared at the point an Action needs it."""

    kind: InputKind
    title: str
    description: str
    label: str
    placeholder: str | None = None
    required: bool = True
    min_length: int = 0
    max_length: int | None = None
    options: tuple[InputOption, ...] = ()
    min_selections: int = 0
    max_selections: int | None = None
