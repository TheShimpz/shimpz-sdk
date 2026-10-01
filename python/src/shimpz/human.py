"""Public value objects for one Action human request."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .message import Text

InputKind = Literal["text", "textarea", "password", "phone", "select", "choice", "choices"]


@dataclass(frozen=True, slots=True)
class InputOption:
    """One closed option displayed by a select, choice, or choices request.

    ``value`` is the canonical, untranslated option value; ``label`` and ``description`` are catalog copy.
    """

    value: str
    label: Text
    description: Text | None = None


@dataclass(frozen=True, slots=True)
class InputRequest:
    """One specialized input prompt declared at the point an Action needs it.

    Every copy field is :func:`shimpz.text` catalog copy; a plain string is refused.
    """

    kind: InputKind
    title: Text
    description: Text
    label: Text
    placeholder: Text | None = None
    required: bool = True
    min_length: int = 0
    max_length: int | None = None
    options: tuple[InputOption, ...] = ()
    min_selections: int = 0
    max_selections: int | None = None
    stored_input: str | None = None
