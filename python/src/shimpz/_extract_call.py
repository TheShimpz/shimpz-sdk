"""Parse one statically readable ``shimpz.text()`` call."""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass

from ._protocol.human_request import COPY_BOUNDS
from ._protocol.message_catalog import FIELD_BOUNDS, PARAM_BOUNDS

CopyField = str
Resolve = Callable[[ast.AST], str | None]
_HELPER_BOUNDS = {"integer": "digits", "domain": "max_length", "dns_name": "max_length", "identifier": "max_length"}
_HELPER_DEFAULTS = {"domain": PARAM_BOUNDS["domain"], "dns_name": PARAM_BOUNDS["dns_name"]}


@dataclass(frozen=True, slots=True)
class MessageUse:
    """One statically extracted message call site and the field bound it must fit."""

    msgid: str
    params: tuple[tuple[str, str, int], ...]
    bound: int
    location: str


class ExtractionError(ValueError):
    """A source construct the static catalog extractor cannot admit, reported with its location."""


def parse_text_call(
    call: ast.Call,
    resolve: Resolve,
    field: CopyField | None,
    location: str,
) -> tuple[MessageUse, list[ast.Call]]:
    """Return the message use of one ``text()`` call and the helper calls it consumes."""

    def fail(message: str) -> ExtractionError:
        return ExtractionError(f"{location}: {message}")

    template = _template(call, fail)
    explicit: int | None = None
    params: list[tuple[str, str, int]] = []
    helpers: list[ast.Call] = []
    for keyword in call.keywords:
        if keyword.arg is None:
            raise fail("text() parameters must be named keyword arguments, not **mappings")
        if keyword.arg == "max_length":
            explicit = _literal_int(keyword.value, fail, "text() max_length")
            if explicit not in FIELD_BOUNDS:
                raise fail("text() max_length must be 80, 120, 160, or 500")
            continue
        helper = keyword.value
        kind = resolve(helper.func) if isinstance(helper, ast.Call) else None
        if kind not in _HELPER_BOUNDS:
            raise fail(
                f"text() parameter {keyword.arg!r} must be written as shimpz.integer(), shimpz.domain(), "
                "shimpz.dns_name(), or shimpz.identifier()"
            )
        params.append((keyword.arg, kind, _helper_bound(helper, kind, fail)))  # type: ignore[arg-type]
        helpers.append(helper)  # type: ignore[arg-type]
    return MessageUse(template, tuple(sorted(params)), _bound(field, explicit, fail), location), helpers


def _template(call: ast.Call, fail: Callable[[str], ExtractionError]) -> str:
    if len(call.args) != 1 or isinstance(call.args[0], ast.Starred):
        raise fail("text() takes exactly one positional template")
    template = call.args[0]
    if isinstance(template, ast.JoinedStr | ast.TemplateStr):
        raise fail("text() template must be a string literal, not an f-string or t-string")
    if not isinstance(template, ast.Constant) or type(template.value) is not str:
        raise fail("text() template must be a string literal; computed templates are refused")
    return template.value


def _helper_bound(helper: ast.Call, kind: str, fail: Callable[[str], ExtractionError]) -> int:
    name = _HELPER_BOUNDS[kind]
    if len(helper.args) != 1 or isinstance(helper.args[0], ast.Starred):
        raise fail(f"shimpz.{kind}() takes exactly one positional value")
    keywords = {keyword.arg: keyword.value for keyword in helper.keywords}
    if None in keywords or set(keywords) - {name} or len(keywords) != len(helper.keywords):
        raise fail(f"shimpz.{kind}() accepts only a literal {name}=")
    if name not in keywords:
        if kind not in _HELPER_DEFAULTS:
            raise fail(f"shimpz.{kind}() requires a literal {name}=")
        return _HELPER_DEFAULTS[kind]
    bound = _literal_int(keywords[name], fail, f"shimpz.{kind}() {name}")
    if not 1 <= bound <= PARAM_BOUNDS[kind]:
        raise fail(f"shimpz.{kind}() {name} must be from 1 to {PARAM_BOUNDS[kind]}")
    return bound


def _literal_int(node: ast.expr, fail: Callable[[str], ExtractionError], label: str) -> int:
    if not isinstance(node, ast.Constant) or type(node.value) is not int:
        raise fail(f"{label} must be an integer literal")
    return node.value


def _bound(field: CopyField | None, explicit: int | None, fail: Callable[[str], ExtractionError]) -> int:
    if field is None:
        if explicit is None:
            raise fail("text() outside a request copy argument requires a literal max_length=")
        return explicit
    bound = COPY_BOUNDS[field]
    if explicit is not None and explicit > bound:
        raise fail(f"text() max_length={explicit} exceeds the {bound}-character {field.replace('_', ' ')} field")
    return bound if explicit is None else explicit
