"""Project one Action failure into the sanitized, bounded Assistant Spec v1 failure envelope."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import quote, quote_plus, urlsplit

from ._protocol.failure_validator import ERROR_TYPE, MAX_PROVIDER, MAX_TEXT_BYTES, PROVIDER, UNSAFE_TEXT, failure_error

REDACTED = "[REDACTED]"
_REPLACEMENT = chr(0xFFFD)
# Provider objects may fail from lazy properties; these ordinary failures withhold that detail and nothing else.
_PROBE_ERRORS = (ArithmeticError, AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError)
# Sanitize at most this much of one text before bounding it. The kept prefix is far shorter than this window minus
# the longest exact secret, so a secret cut at the window edge can never reach the bounded output.
_WINDOW = 64 * 1_024
_MAX_CHAIN = 8
_TEXT_MEDIA = re.compile(r"(?:text/[\w.+-]+|application/(?:[\w.-]+\+)?(?:json|xml)|application/x-www-form-urlencoded)")
_NAMED_SECRET = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|authorization"
    r"|cookie|session[_-]?id|signature|credential|(?<![A-Za-z])key)[\w.-]{0,32}(?P<separator>[\"']?\s{0,4}[:=]\s{0,4}[\"']?)"
    r"(?P<value>(?!\[REDACTED\])(?:(?:bearer|basic|token)\s+)?[^\s\"'&,;)}\]<>]{1,4096})"
)
_SHAPED_SECRETS = (
    re.compile(r"(?i)\b(?P<keep>(?:bearer|basic|digest|token)\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?P<keep>[a-z][a-z0-9+.-]{0,31}://)[^\s/@:]{0,256}(?::[^\s/@]{0,256})?@"),
    re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]{0,40}PRIVATE KEY-----|[\s\S]*)"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
    re.compile(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abposr]-[A-Za-z0-9-]{10,})"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{35}"),
)


class Sanitizer:
    """Replace every exact invocation secret and secret-shaped text, recording whether anything was withheld."""

    __slots__ = ("_secrets", "redacted")

    def __init__(self, secrets: Iterable[str]) -> None:
        variants = {
            form
            for secret in secrets
            if isinstance(secret, str) and secret
            for form in (secret, quote(secret, safe=""), quote_plus(secret, safe=""))
        }
        self._secrets = sorted(variants, key=len, reverse=True)
        self.redacted = False

    def text(self, value: str, limit: int = MAX_TEXT_BYTES) -> tuple[str, bool]:
        """Return sanitized safe text within ``limit`` UTF-8 bytes and whether it was truncated."""
        window = value[:_WINDOW]
        for secret in self._secrets:
            if secret in window:
                window = window.replace(secret, REDACTED)
                self.redacted = True
        window = self._shaped(window)
        bounded, cut = _bounded(_safe_characters(window), limit)
        return bounded, cut or len(value) > _WINDOW

    def _shaped(self, value: str) -> str:
        value, count = _NAMED_SECRET.subn(
            lambda match: match.string[match.start() : match.start("value")] + REDACTED, value
        )
        self.redacted |= count > 0
        for pattern in _SHAPED_SECRETS:
            value, count = pattern.subn(_replace, value)
            self.redacted |= count > 0
        return value


def failure_envelope(error: BaseException, secrets: Iterable[str]) -> dict[str, object]:
    """Return the failure envelope for ``error``; it never raises and never carries an unsanitized value."""
    sanitizer = Sanitizer(secrets)
    try:
        failure = _failure(error, sanitizer)
    except _PROBE_ERRORS:
        failure = None
    envelope = {"type": "failure", "failure": failure}
    if failure is None or failure_error(envelope) is not None:
        envelope["failure"] = _fallback(error)
    return envelope


def _failure(error: BaseException, sanitizer: Sanitizer) -> dict[str, object]:
    message, message_cut = sanitizer.text(_message(error))
    response, status, provider = _provider_details(error)
    excerpt, excerpt_cut = None, False
    if response is not None:
        body = _body(response)
        if body is None:
            sanitizer.redacted = True
        else:
            excerpt, excerpt_cut = sanitizer.text(body)
    error_type, _ = sanitizer.text(_type_name(error), 128)
    return {
        "error_type": _ascii_word(error_type),
        "message": message,
        "provider": provider,
        "http_status": status,
        "response_excerpt": excerpt,
        "redacted": sanitizer.redacted,
        "truncated": message_cut or excerpt_cut,
    }


def _fallback(error: BaseException) -> dict[str, object]:
    return {
        "error_type": _ascii_word(_type_name(error)),
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


def _ascii_word(value: str) -> str:
    word = "".join(character if "!" <= character <= "~" else "?" for character in value)[:128]
    return word if ERROR_TYPE.fullmatch(word) else "Exception"


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


def _safe_characters(value: str) -> str:
    """Normalize line breaks and replace every unsafe or unpaired surrogate character with U+FFFD."""
    value = UNSAFE_TEXT.sub(_REPLACEMENT, value.replace("\r\n", "\n"))
    return "".join(_REPLACEMENT if 0xD800 <= ord(character) <= 0xDFFF else character for character in value)


def _bounded(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value, False
    return encoded[:limit].decode("utf-8", "ignore"), True


def _replace(match: re.Match[str]) -> str:
    keep = match.groupdict().get("keep")
    return f"{keep}{REDACTED}" if keep else REDACTED
