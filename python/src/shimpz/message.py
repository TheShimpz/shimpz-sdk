"""English catalog copy for Action human requests.

Every user-visible request string is a :class:`Text` built by :func:`text` from an English string literal. The
Shimpz extractor reads each ``text()`` call statically, so the template and every parameter kind and maximum must be
literal arguments written directly in the call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ParamKind = Literal["integer", "domain", "identifier"]
FIELD_BOUNDS = (80, 120, 160, 500)
_PARAM_BOUNDS = {"integer": 15, "domain": 253, "identifier": 128}


@dataclass(frozen=True, slots=True)
class Param:
    """One bounded message parameter value of a closed kind."""

    kind: ParamKind
    value: int | str
    max_length: int


@dataclass(frozen=True, slots=True)
class Text:
    """One immutable English catalog message with its parameter values."""

    template: str
    params: tuple[tuple[str, Param], ...] = ()
    max_length: int | None = None


def text(template: str, /, *, max_length: int | None = None, **params: Param) -> Text:
    """Return catalog copy for a literal English template and its kind-wrapped parameters.

    ``max_length`` is required, as a literal, when the call is not written directly as a request copy argument.
    """
    if type(template) is not str:
        raise TypeError("text() template must be an English string literal")
    if max_length is not None and (type(max_length) is not int or max_length not in FIELD_BOUNDS):
        raise ValueError("text() max_length must be 80, 120, 160, or 500")
    if not all(isinstance(value, Param) for value in params.values()):
        raise TypeError("text() parameters must use shimpz.integer, shimpz.domain, or shimpz.identifier")
    return Text(template=template, params=tuple(sorted(params.items())), max_length=max_length)


def integer(value: int, *, digits: int) -> Param:
    """Return a non-negative integer parameter of at most ``digits`` decimal digits (at most 15)."""
    if type(value) is not int:
        raise TypeError("shimpz.integer() value must be an int")
    return Param("integer", value, _bound("integer", digits))


def domain(value: str, *, max_length: int = 253) -> Param:
    """Return a lowercase DNS name parameter of at most ``max_length`` characters (at most 253)."""
    if type(value) is not str:
        raise TypeError("shimpz.domain() value must be a str")
    return Param("domain", value, _bound("domain", max_length))


def identifier(value: str, *, max_length: int) -> Param:
    """Return an opaque ``[A-Za-z0-9][A-Za-z0-9._:-]*`` parameter of at most ``max_length`` characters (at most 128)."""
    if type(value) is not str:
        raise TypeError("shimpz.identifier() value must be a str")
    return Param("identifier", value, _bound("identifier", max_length))


def _bound(kind: str, maximum: object) -> int:
    if type(maximum) is not int or not 1 <= maximum <= _PARAM_BOUNDS[kind]:
        raise ValueError(f"shimpz.{kind}() maximum must be an int from 1 to {_PARAM_BOUNDS[kind]}")
    return maximum
