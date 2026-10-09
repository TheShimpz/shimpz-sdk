"""Assemble and validate the English message catalog from extracted message uses."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._extract import extract
from ._extract_call import ExtractionError, MessageUse
from ._protocol.message_catalog import (
    DESCRIPTION_BOUND,
    LINE_BOUND,
    SUMMARY_BOUND,
    catalog_error,
    display_error,
    display_uses,
    message_error,
    message_id,
    placeholders,
)

Message = dict[str, object]


@dataclass(frozen=True, slots=True)
class DisplayCopy:
    """The manifest's displayed static copy: the summary, the description, and each Stored Input label by id."""

    summary: str
    description: str
    labels: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any]) -> DisplayCopy:
        """Read the displayed copy of an already validated ``shimpz.toml``."""
        shimpz, stored = manifest["shimpz"], manifest.get("stored_inputs", {})
        labels = tuple(sorted((stored_id, declaration["label"]) for stored_id, declaration in stored.items()))
        return cls(shimpz["summary"], shimpz["description"], labels)

    def uses(self) -> tuple[MessageUse, ...]:
        """Return each displayed manifest text as a parameterless use within its catalog bound."""
        return (
            MessageUse(self.summary, (), SUMMARY_BOUND, "shimpz.toml summary"),
            MessageUse(self.description, (), DESCRIPTION_BOUND, "shimpz.toml description"),
            *(
                MessageUse(label, (), LINE_BOUND, f"shimpz.toml stored_inputs.{stored_id}.label")
                for stored_id, label in self.labels
            ),
        )


@dataclass(frozen=True, slots=True)
class StaticCatalog:
    """The statically extracted English catalog and each Action file's literal description."""

    messages: list[Message]
    descriptions: dict[Path, str]


def load_catalog(root: Path, action_files: Sequence[Path], copy: DisplayCopy) -> StaticCatalog:
    """Statically extract the catalog of the Action files and ``lib/**/*.py`` without importing them."""
    library = root / "lib"
    lib_files = sorted(library.rglob("*.py")) if library.is_dir() else []
    uses, descriptions = extract(root, action_files, lib_files)
    messages = build_catalog(uses, tuple(descriptions.values()), copy)
    return StaticCatalog(messages, {path: use.msgid for path, use in descriptions.items()})


def build_catalog(uses: Sequence[MessageUse], actions: Sequence[MessageUse], copy: DisplayCopy) -> list[Message]:
    """Return the sorted catalog of every use, Action description, and displayed manifest text.

    One message serves every use of its template and carries the smallest bound of them all; a template used with
    other parameters is refused, as is anything else Developers refuses.
    """
    displayed_uses = (*actions, *copy.uses())
    for use in displayed_uses:
        if "{" in use.msgid or "}" in use.msgid:
            raise ExtractionError(f"{use.location}: displayed copy takes no parameters, so braces are refused")
    declarations: dict[str, MessageUse] = {}
    bounds: dict[str, int] = {}
    for use in (*uses, *displayed_uses):
        _check_use(use)
        first = declarations.setdefault(use.msgid, use)
        if first.params != use.params:
            raise ExtractionError(f"{use.location}: message is declared with other parameters at {first.location}")
        bounds[use.msgid] = min(bounds.get(use.msgid, use.bound), use.bound)
    messages = sorted(
        (_entry(msgid, use.params, bounds[msgid]) for msgid, use in declarations.items()),
        key=lambda message: str(message["id"]),
    )
    displayed = display_uses(copy.description, [use.msgid for use in actions], [label for _, label in copy.labels])
    error = catalog_error(messages, copy.summary) or display_error(messages, displayed)
    if error is not None:
        raise ExtractionError(f"message catalog is invalid: {error}")
    return messages


def _entry(msgid: str, params: tuple[tuple[str, str, int], ...], bound: int) -> Message:
    return {
        "id": message_id(msgid),
        "msgid": msgid,
        "max_length": bound,
        "params": [{"name": name, "kind": kind, "max_length": maximum} for name, kind, maximum in params],
    }


def _check_use(use: MessageUse) -> None:
    error = message_error(_entry(use.msgid, use.params, use.bound))
    if error is None:
        return
    raise ExtractionError(f"{use.location}: {_reason(use, error)}")


def _reason(use: MessageUse, error: str) -> str:
    if error == "message_placeholders":
        return _placeholder_reason(use)
    if error == "public_text" and not unicodedata.is_normalized("NFC", use.msgid):
        return "message template must be NFC-normalized"
    reasons = {
        "public_text": "message template must be trimmed printable text of 1 to 500 characters without format controls",
        "message_budget": _budget_reason(use),
        "message_params": "message parameters must be at most 8 names matching [a-z][a-z0-9_]{0,31}",
    }
    return reasons.get(error, f"message is invalid: {error}")


def _budget_reason(use: MessageUse) -> str:
    literal = len(use.msgid) - sum(len(name) + 2 for name, _, _ in use.params)
    maxima = " + ".join(f"{name} {maximum}" for name, _, maximum in use.params)
    total = literal + sum(maximum for _, _, maximum in use.params)
    return (
        f"message does not fit its {use.bound}-character field: {literal} literal characters"
        f"{f' + parameter maxima ({maxima})' if maxima else ''} = {total}"
    )


def _placeholder_reason(use: MessageUse) -> str:
    names = placeholders(use.msgid)
    if names is None:
        return "message placeholders must be {name} fields only; other braces and format syntax are refused"
    if len(names) != len(set(names)):
        return "message placeholders must each appear once"
    if set(names) != {name for name, _, _ in use.params}:
        return "message placeholders must match the text() parameters exactly"
    return "a combining mark must not directly follow a message placeholder"
