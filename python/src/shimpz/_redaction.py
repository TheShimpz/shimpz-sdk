"""Remove every known invocation secret and secret-shaped text from one failure diagnostic, then bound it."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable
from urllib.parse import quote, quote_plus

from ._protocol.failure import MAX_TEXT_BYTES, UNSAFE_TEXT

REDACTED = "[REDACTED]"
_REPLACEMENT = chr(0xFFFD)
# Sanitize at most this many characters of one text. Longer text is withheld whole: replacing secrets inside a
# clipped prefix could shorten it enough to bring a clipped secret into the bounded output. Within the window, every
# secret-shaped pattern consumes its whole value, because an upper bound would leave a longer secret's tail behind.
WINDOW = 64 * 1_024
_NAMED_SECRET = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|authorization"
    r"|cookie|session[_-]?id|signature|credential|(?<![A-Za-z])key)[\w.-]{0,32}(?P<separator>[\"']?\s*[:=]\s*)"
    # A quoted value is consumed whole up to its unescaped closing quote, or to the end when that quote is missing.
    r"(?:(?P<quote>[\"'])(?P<quoted>(?!\[REDACTED\](?P=quote))(?:\\[\s\S]?|(?!(?P=quote))[^\\])*)(?P=quote)?"
    r"|(?P<value>(?!\[REDACTED\])(?:(?:bearer|basic|token)\s+)?[^\s\"'&,;)}\]<>]+))"
)
_SHAPED_SECRETS = (
    re.compile(r"(?i)\b(?P<keep>(?:bearer|basic|digest|token)\s+)[A-Za-z0-9._~+/=-]{8,}"),
    # URL user information runs to the last "@" of the authority, as urllib splits it.
    re.compile(r"(?i)\b(?P<keep>[a-z][a-z0-9+.-]{0,31}://)[^\s/?#]*@"),
    # An unquoted cookie list carries several named credentials, so its whole line is withheld.
    re.compile(r"(?i)\b(?P<keep>cookies?[\w.-]{0,32}[\"']?\s*[:=]\s*)(?![\"'])[^\r\n]+"),
    re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]{0,40}PRIVATE KEY-----|[\s\S]*)"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
    re.compile(r"\b(?:sk|rk|pk)[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abposr]-[A-Za-z0-9-]{10,})"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{35,}"),
)


class Sanitizer:
    """Sanitize every diagnostic string of one failure, accumulating whether anything was withheld or cut."""

    __slots__ = ("_known", "redacted", "truncated")

    def __init__(self, secrets: Iterable[str]) -> None:
        forms = {form for secret in secrets if isinstance(secret, str) and secret for form in _encodings(secret)}
        # Case-insensitive matching also covers lowercase percent-escapes and case-changed hex or ASCII tokens.
        self._known = [re.compile(re.escape(form), re.IGNORECASE) for form in sorted(forms, key=len, reverse=True)]
        self.redacted = False
        self.truncated = False

    def text(self, value: str, limit: int = MAX_TEXT_BYTES) -> str | None:
        """Return safe text within ``limit`` UTF-8 bytes, or ``None`` when it is too long to sanitize."""
        if len(value) > WINDOW:
            self.redacted = self.truncated = True
            return None
        for pattern in self._known:
            value = self._substitute(pattern, REDACTED, value)
        value = self._substitute(_NAMED_SECRET, _keep_name, value)
        for pattern in _SHAPED_SECRETS:
            value = self._substitute(pattern, _replace, value)
        value = self._substitute(_UNSAFE, _REPLACEMENT, value.replace("\r\n", "\n"))
        encoded = value.encode("utf-8")
        if len(encoded) <= limit:
            return value
        self.truncated = True
        return encoded[:limit].decode("utf-8", "ignore")

    def _substitute(self, pattern: re.Pattern[str], replacement: object, value: str) -> str:
        value, count = pattern.subn(replacement, value)
        self.redacted |= count > 0
        return value


def _encodings(secret: str) -> set[str]:
    """The exact value and its common encodings: percent, form, JSON string, and standard or URL-safe base64."""
    raw = secret.encode("utf-8", "surrogatepass")
    forms = {
        secret,
        quote(secret, safe=""),
        quote_plus(secret, safe=""),
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
    }
    for encoded in (base64.b64encode(raw), base64.urlsafe_b64encode(raw)):
        forms |= {encoded.decode("ascii"), encoded.decode("ascii").rstrip("=")}
    return {form for form in forms if form}


# Every unsafe character and every unpaired surrogate becomes U+FFFD.
_UNSAFE = re.compile(UNSAFE_TEXT.pattern[:-1] + r"\ud800-\udfff]")


def _keep_name(match: re.Match[str]) -> str:
    if match["quote"] is None:
        return match.string[match.start() : match.start("value")] + REDACTED
    # Keep the opening quote, and the closing quote only when the text had one.
    return (
        match.string[match.start() : match.start("quoted")] + REDACTED + match.string[match.end("quoted") : match.end()]
    )


def _replace(match: re.Match[str]) -> str:
    keep = match.groupdict().get("keep")
    return f"{keep}{REDACTED}" if keep else REDACTED
