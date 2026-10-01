"""Assemble and validate the English message catalog from extracted message uses."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from pathlib import Path

from ._extract import extract
from ._extract_call import ExtractionError, MessageUse
from ._protocol.message_catalog_validator import (
    SUMMARY_BOUND,
    catalog_error,
    message_error,
    message_id,
    placeholders,
)

Message = dict[str, object]


def load_catalog(root: Path, action_files: Sequence[Path], summary: str) -> list[Message]:
    """Statically extract the catalog of the Action files and ``lib/**/*.py`` without importing them."""
    library = root / "lib"
    lib_files = sorted(library.rglob("*.py")) if library.is_dir() else []
    return build_catalog(extract(root, [*action_files, *lib_files]), summary)


def build_catalog(uses: Sequence[MessageUse], summary: str) -> list[Message]:
    """Return the sorted catalog for every use plus the manifest summary, refusing what Developers refuses."""
    declarations: dict[str, MessageUse] = {}
    bounds: dict[str, int] = {summary: SUMMARY_BOUND}
    for use in (*uses, MessageUse(summary, (), SUMMARY_BOUND, "shimpz.toml summary")):
        _check_use(use)
        first = declarations.setdefault(use.msgid, use)
        if first.params != use.params:
            raise ExtractionError(f"{use.location}: message is declared with other parameters at {first.location}")
        bounds[use.msgid] = min(bounds.get(use.msgid, use.bound), use.bound)
    messages = sorted(
        (_entry(msgid, use.params, bounds[msgid]) for msgid, use in declarations.items()),
        key=lambda message: str(message["id"]),
    )
    error = catalog_error(messages, summary)
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
        "message_budget": f"message does not fit its {use.bound}-character field with its parameter maxima",
        "message_params": "message parameters must be at most 8 names matching [a-z][a-z0-9_]{0,31}",
    }
    return reasons.get(error, f"message is invalid: {error}")


def _placeholder_reason(use: MessageUse) -> str:
    names = placeholders(use.msgid)
    if names is None:
        return "message placeholders must be {name} fields only; other braces and format syntax are refused"
    if len(names) != len(set(names)):
        return "message placeholders must each appear once"
    if set(names) != {name for name, _, _ in use.params}:
        return "message placeholders must match the text() parameters exactly"
    return "a combining mark must not directly follow a message placeholder"
