"""Deterministic, invocation-local Action human-request replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

MAX_REQUESTS = 8


class HumanRequestSuspension(Exception):
    """Private control signal carrying one bounded request frame."""

    def __init__(self, request: dict[str, object]) -> None:
        super().__init__("Action requested human input")
        self.request = request


class HumanRequestRuntime:
    """Match one Action execution against its Team-admitted response transcript."""

    __slots__ = ("_allowed", "_authorization_requested", "_index", "_responses", "_secret", "_token_observed")

    def __init__(self, allowed: Sequence[str], responses: Sequence[Mapping[str, object]]) -> None:
        if len(responses) > MAX_REQUESTS:
            raise ValueError("Action human response transcript is invalid")
        self._allowed = frozenset(allowed)
        self._authorization_requested = False
        self._responses = tuple(dict(item) for item in responses)
        self._index = 0
        self._secret: str | None = None
        self._token_observed = False

    def observe_token(self) -> None:
        """Record the first access to an Integration bearer."""
        self._token_observed = True

    def resolve(self, kind: str, descriptor: dict[str, object]) -> object:
        """Return one matching admitted response or suspend with its canonical request."""
        if kind not in self._allowed:
            raise ValueError("Action human request capability is undeclared")
        if self._token_observed:
            raise ValueError("Action cannot request human input after observing an Integration token")
        if self._secret is not None:
            raise ValueError("Action password input must be its final human request")
        if kind == "approval" or kind.startswith("auth:"):
            if self._authorization_requested:
                raise ValueError("Action can request authorization only once")
            self._authorization_requested = True
        if self._index >= MAX_REQUESTS:
            raise ValueError("Action exceeded its human request limit")
        request = {"kind": kind, "ordinal": self._index, **descriptor}
        fingerprint = _fingerprint(request)
        framed = {**request, "fingerprint": fingerprint}
        if self._index == len(self._responses):
            raise HumanRequestSuspension(framed)
        response = self._responses[self._index]
        _match_response(response, kind, self._index, fingerprint)
        value = response["value"]
        _validate_value(kind, descriptor, value)
        self._index += 1
        if kind == "input:password":
            if not isinstance(value, str):
                raise ValueError("Action human input response is invalid")
            self._secret = value
        return value

    def finish(self, result: object) -> None:
        """Reject an unused response or exact password echo in the Action result."""
        if self._index != len(self._responses):
            raise ValueError("Action human response transcript diverged")
        if self._secret and _contains(result, self._secret):
            raise ValueError("Action result exposes human password input")


def _fingerprint(request: object) -> str:
    try:
        encoded = json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("Action human request is invalid") from error
    return hashlib.sha256(encoded).hexdigest()


def _match_response(
    response: Mapping[str, object],
    kind: str,
    ordinal: int,
    fingerprint: str,
) -> None:
    if (
        set(response) != {"kind", "ordinal", "fingerprint", "value"}
        or response.get("kind") != kind
        or response.get("ordinal") != ordinal
        or response.get("fingerprint") != fingerprint
    ):
        raise ValueError("Action human response transcript diverged")


def _validate_value(kind: str, descriptor: Mapping[str, object], value: object) -> None:
    if kind == "approval" or kind.startswith("auth:"):
        if value is not True:
            raise ValueError("Action human authorization response is invalid")
        return
    if kind == "input:choices":
        _validate_choices(descriptor, value)
        return
    if not isinstance(value, str):
        raise ValueError("Action human input response is invalid")
    if kind in {"input:select", "input:choice"}:
        if value == "" and descriptor["required"] is False:
            return
        allowed = {item["value"] for item in descriptor["options"]}  # type: ignore[index]
        if value not in allowed:
            raise ValueError("Action human input response is invalid")
        return
    minimum = descriptor["min_length"]
    maximum = descriptor["max_length"]
    required = descriptor["required"]
    if not isinstance(minimum, int) or not isinstance(maximum, int):
        raise ValueError("Action human input response is invalid")
    if (required and not value) or not minimum <= len(value) <= maximum:
        raise ValueError("Action human input response is invalid")


def _validate_choices(descriptor: Mapping[str, object], value: object) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Action human choices response is invalid")
    if len(value) != len(set(value)):
        raise ValueError("Action human choices response is invalid")
    allowed = {item["value"] for item in descriptor["options"]}  # type: ignore[index]
    minimum = descriptor["min_selections"]
    maximum = descriptor["max_selections"]
    if (
        not set(value) <= allowed
        or not isinstance(minimum, int)
        or not isinstance(maximum, int)
        or not minimum <= len(value) <= maximum
    ):
        raise ValueError("Action human choices response is invalid")


def _contains(value: object, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, Mapping):
        return any(_contains(key, secret) or _contains(item, secret) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, bytes):
        return any(_contains(item, secret) for item in value)
    return False
