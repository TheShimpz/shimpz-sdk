"""Verify a prepared language pack against a project's statically extracted catalog (ADR-0091)."""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from ._project import load_catalog_document
from ._protocol.message_catalog import MAX_PACK_BYTES, catalog_digest, pack_digest, pack_error

if TYPE_CHECKING:
    from pathlib import Path


class PackRefusedError(ValueError):
    """A pack the reference validator refuses; the message is only its closed error code."""


def read_pack(source: BinaryIO) -> bytes:
    """Read the exact pack bytes without decoding or newline translation, within the pack bound."""
    raw = source.read(MAX_PACK_BYTES + 1)
    if not isinstance(raw, bytes) or len(raw) > MAX_PACK_BYTES:
        raise PackRefusedError("pack_bytes")
    return raw


def verify_pack(root: Path, raw: bytes) -> dict[str, str]:
    """Admit exact pack bytes for the project's catalog, extracted without importing Creator code."""
    messages = load_catalog_document(root)["messages"]
    error = pack_error(raw, messages)  # type: ignore[arg-type]
    if error is not None:
        raise PackRefusedError(error)
    return {"catalog": catalog_digest(messages), "pack": pack_digest(raw)}  # type: ignore[arg-type]
