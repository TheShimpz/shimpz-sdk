"""Project one Action failure into the sanitized, bounded Assistant Spec v1 failure envelope."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from ._protocol.failure import ERROR_TYPE, MAX_PROVIDER, PROVIDER, failure_error
from ._redaction import Sanitizer

# A fallback never reflects the failed projection, not even its exception type.
FALLBACK_TYPE = "Exception"
# Provider objects may fail from lazy properties; these ordinary failures withhold that detail and nothing else.
_PROBE_ERRORS = (ArithmeticError, AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError)
_MAX_CHAIN = 8
_TEXT_MEDIA = re.compile(r"(?:text/[\w.+-]+|application/(?:[\w.-]+\+)?(?:json|xml)|application/x-www-form-urlencoded)")


def failure_envelope(error: BaseException, secrets: Iterable[str], *, withhold_text: bool = False) -> dict[str, object]:
    """Return the failure envelope for ``error``; it never raises and never carries an unsanitized value.

    ``withhold_text`` drops the free-text message and provider excerpt, for an invocation bound to a Team file whose
    name and content no exact redaction can find inside arbitrary text (ADR-0093).
    """
    sanitizer = Sanitizer(secrets)
    try:
        failure = _failure(error, sanitizer)
    except _PROBE_ERRORS:
        failure = None
    if failure is not None and withhold_text:
        failure.update(message="", response_excerpt=None, redacted=True, truncated=False)
    envelope = {"type": "failure", "failure": failure}
    if failure is None or failure_error(envelope) is not None:
        envelope["failure"] = _fallback()
    return envelope


def _failure(error: BaseException, sanitizer: Sanitizer) -> dict[str, object]:
    message = sanitizer.text(_message(error))
    response, status, host = _provider_details(error)
    excerpt = None
    if response is not None:
        body = _body(response)
        if body is None:
            sanitizer.redacted = True
        else:
            excerpt = sanitizer.text(body)
    provider = sanitizer.text(host) if host is not None else None
    if provider != host:
        sanitizer.redacted = True
        provider = None
    return {
        "error_type": _error_type(error, sanitizer),
        "message": message or "",
        "provider": provider,
        "http_status": status,
        "response_excerpt": excerpt,
        "redacted": sanitizer.redacted,
        "truncated": sanitizer.truncated,
    }


def _error_type(error: BaseException, sanitizer: Sanitizer) -> str:
    """The real type name, sanitized like every other string, as one printable ASCII word of at most 128."""
    name = sanitizer.text(_type_name(error), 4 * 128) or ""
    word = "".join(character if "!" <= character <= "~" else "?" for character in name)
    sanitizer.redacted |= word != name
    sanitizer.truncated |= len(word) > 128
    word = word[:128]
    if ERROR_TYPE.fullmatch(word) is None:
        sanitizer.redacted = True
        return FALLBACK_TYPE
    return word


def _fallback() -> dict[str, object]:
    return {
        "error_type": FALLBACK_TYPE,
        "message": "",
        "provider": None,
        "http_status": None,
        "response_excerpt": None,
        "redacted": True,
        "truncated": False,
    }


def _message(error: BaseException) -> str:
    try:
        return str(error)
    except _PROBE_ERRORS:
        return ""


def _type_name(error: BaseException) -> str:
    kind = type(error)
    module = getattr(kind, "__module__", "")
    name = getattr(kind, "__qualname__", "") or getattr(kind, "__name__", "")
    return name if module in {"builtins", ""} else f"{module}.{name}"


def _provider_details(error: BaseException) -> tuple[object | None, int | None, str | None]:
    """Find the first provider response or request along the exception's cause and context chain."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(seen) < _MAX_CHAIN:
        seen.add(id(current))
        response = _attribute(current, "response")
        request = _attribute(current, "request") or _attribute(current, "request_info")
        if response is not None or request is not None:
            status = _status(response) if response is not None else None
            status = status if status is not None else _status(current)
            return response, status, _host(response, request)
        current = current.__cause__ or current.__context__
    return None, None, None


def _attribute(value: object, name: str) -> object | None:
    try:
        return getattr(value, name, None)
    except _PROBE_ERRORS:
        return None


def _status(value: object) -> int | None:
    for name in ("status_code", "status"):
        status = _attribute(value, name)
        if type(status) is int and 100 <= status <= 599:
            return status
    return None


def _host(response: object | None, request: object | None) -> str | None:
    for owner in (_attribute(response, "request") if response is not None else None, request, response):
        url = _attribute(owner, "url") if owner is not None else None
        if url is None:
            continue
        try:
            host = urlsplit(str(url)).hostname
        except ValueError:
            continue
        if host and len(host) <= MAX_PROVIDER and PROVIDER.fullmatch(host):
            return host
    return None


def _body(response: object) -> str | None:
    """Return a textual provider body, or ``None`` when it is unavailable or not text and is therefore withheld."""
    headers = _attribute(response, "headers")
    media = ""
    try:
        media = str(headers.get("content-type", "")) if headers is not None else ""
    except _PROBE_ERRORS:
        return None
    if media and _TEXT_MEDIA.match(media.strip().lower()) is None:
        return None
    text = _attribute(response, "text")
    return text if isinstance(text, str) else None
