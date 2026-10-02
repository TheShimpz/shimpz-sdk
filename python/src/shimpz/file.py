"""One Team file delivered to an Action input declared as ``shimpz.File`` (ADR-0093)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


class FileContentWithheldError(RuntimeError):
    """Raised when an Action reads file bytes before its authorization is granted in this execution.

    Team delivers the original bytes only on the replay that follows the Action's declared authorization, and the SDK
    exposes them only after that replay matches the authorization response, so read them after
    ``ctx.request_approval`` or ``ctx.request_auth`` returns.
    """


@dataclass(frozen=True, slots=True)
class File:
    """One immutable Team file selected for this invocation.

    The metadata is always present. The original bytes, at most 8 MiB, exist only after the Action's declared
    authorization; ``read`` raises ``FileContentWithheldError`` until then and never returns an empty substitute.
    ``name`` is the literal Team filename, never a path, and ``media_type`` is the type Team determined from the bytes.
    """

    id: str
    name: str
    media_type: str
    size: int
    sha256: str
    _content: bytes | None = field(default=None, repr=False, compare=False)
    _authorized: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    @property
    def delivered(self) -> bool:
        """Return whether Team delivered the original bytes to this invocation."""
        return self._content is not None

    def read(self) -> bytes:
        """Return the original bytes, which exist only after the Action's authorization matched in this execution."""
        if self._content is None or (self._authorized is not None and not self._authorized()):
            message = "file content is withheld until the Action's authorization is granted"
            raise FileContentWithheldError(message)
        return self._content
