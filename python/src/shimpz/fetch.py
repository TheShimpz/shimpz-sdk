"""Provider calls an Action asks Team to make, so the Action never holds a credential (ADR-0106)."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TextIO

from ._json import strict_loads

METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
MAX_CALLS = 16
MAX_BODY_BYTES = 256 * 1024
MAX_TIMEOUT_MS = 30_000
# Team's largest reply: a 4 MiB body in base64 plus at most 64 bounded headers.
_MAX_REPLY_CHARS = 6 * 1024 * 1024
_ERRORS = frozenset({"refused", "credential-missing", "unavailable", "failed"})

Headers = Mapping[str, str] | Sequence[tuple[str, str]]


class FetchError(Exception):
    """Team made no usable provider call; ``code`` is ``refused``, ``credential-missing``, ``unavailable``, or ``failed``.

    ``refused`` means the call broke the Assistant's declarations or the bounds, ``credential-missing`` that Team holds
    no declared credential for that host, ``unavailable`` that the provider could not be reached, and ``failed`` that
    Team refused or could not complete its response.
    """

    def __init__(self, code: str) -> None:
        super().__init__(f"provider call {code}")
        self.code = code


@dataclass(frozen=True, slots=True)
class Response:
    """One complete provider response Team released to the Action."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def header(self, name: str) -> str | None:
        """Return the first value of one header, compared without case, or ``None``."""
        folded = name.lower()
        return next((value for key, value in self.headers if key.lower() == folded), None)

    def text(self) -> str:
        """Return the body decoded as UTF-8."""
        return self.body.decode()

    def json(self) -> object:
        """Return the body parsed as strict JSON."""
        return strict_loads(self.body.decode())


class ProviderChannel:
    """The Action's half of its exec channel: one request line out, exactly one reply line back."""

    __slots__ = ("_calls", "_sink", "_source")

    def __init__(self, source: TextIO, sink: TextIO) -> None:
        self._source = source
        self._sink = sink
        self._calls = 0

    def call(self, frame: dict[str, object]) -> Response:
        """Send one provider-call frame and return Team's response, or raise ``FetchError``."""
        if self._calls >= MAX_CALLS:
            raise FetchError("refused")
        self._calls += 1
        self._sink.write(json.dumps(frame, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
        self._sink.flush()
        raw = self._source.readline(_MAX_REPLY_CHARS + 1)
        if not raw.endswith("\n"):
            raise ValueError("provider call reply is invalid")
        return _response(strict_loads(raw))


def request_frame(
    method: str,
    url: str,
    headers: Headers,
    body: bytes | str | None,
    timeout_ms: int | None,
) -> dict[str, object]:
    """Return one bounded provider-call frame; Team still decides every rule it enforces."""
    pairs = list(headers.items() if isinstance(headers, Mapping) else headers)
    payload = body.encode() if isinstance(body, str) else body
    if (
        method not in METHODS
        or not isinstance(url, str)
        or not url.startswith("https://")
        or not all(isinstance(pair, tuple) and len(pair) == 2 and all(isinstance(part, str) for part in pair) for pair in pairs)
        or (payload is not None and (not isinstance(payload, bytes) or len(payload) > MAX_BODY_BYTES))
        or (timeout_ms is not None and (type(timeout_ms) is not int or not 0 < timeout_ms <= MAX_TIMEOUT_MS))
    ):
        raise ValueError("provider call is invalid")
    frame: dict[str, object] = {"type": "fetch", "method": method, "url": url, "headers": [list(pair) for pair in pairs]}
    if payload is not None:
        frame["body"] = base64.b64encode(payload).decode("ascii")
    if timeout_ms is not None:
        frame["timeout_ms"] = timeout_ms
    return frame


def _response(reply: object) -> Response:
    if isinstance(reply, dict) and set(reply) == {"error"} and reply["error"] in _ERRORS:
        raise FetchError(reply["error"])
    if not isinstance(reply, dict) or set(reply) != {"status", "headers", "body"}:
        raise ValueError("provider call reply is invalid")
    status, headers, body = reply["status"], reply["headers"], reply["body"]
    if (
        type(status) is not int
        or not 100 <= status <= 599
        or not isinstance(headers, list)
        or not all(isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair) for pair in headers)
        or not isinstance(body, str)
    ):
        raise ValueError("provider call reply is invalid")
    try:
        content = base64.b64decode(body, validate=True)
    except binascii.Error as error:
        raise ValueError("provider call reply is invalid") from error
    return Response(status, tuple((name, value) for name, value in headers), content)
