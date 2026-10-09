"""Deterministic, invocation-local Action human-request replay."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ._protocol.human_request import fingerprint, request_error

MAX_REQUESTS = 8


class HumanRequestSuspension(Exception):
    """Private control signal carrying one bounded request frame."""

    def __init__(self, request: dict[str, object]) -> None:
        super().__init__("Action requested human input")
        self.request = request


class StoredInputRejection(Exception):
    """Private control signal rejecting one exact resolved Stored Input."""

    def __init__(self, stored_input: str) -> None:
        super().__init__("Action rejected a Stored Input")
        self.stored_input = stored_input


class HumanRequestRuntime:
    """Match one Action execution against its Team-admitted response transcript."""

    __slots__ = (
        "_allowed",
        "_authorization_requested",
        "_authorized",
        "_called",
        "_catalog",
        "_index",
        "_resolved_stored_inputs",
        "_responses",
        "_stored_inputs",
    )

    def __init__(
        self,
        allowed: Sequence[str],
        responses: Sequence[Mapping[str, object]],
        stored_inputs: Iterable[str] = (),
        catalog: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        if len(responses) > MAX_REQUESTS:
            raise ValueError("Action human response transcript is invalid")
        self._allowed = frozenset(allowed)
        self._catalog = dict(catalog or {})
        self._authorization_requested = False
        self._authorized = False
        self._responses = tuple(dict(item) for item in responses)
        self._index = 0
        self._stored_inputs = frozenset(stored_inputs)
        self._resolved_stored_inputs: set[str] = set()
        self._called = False

    def authorized(self) -> bool:
        """Return whether this execution matched its authorization request to the admitted response."""
        return self._authorized

    def observe_call(self) -> None:
        """Record the first provider call, after which a replay could repeat it, so no human request may follow."""
        self._called = True

    def resolve(self, kind: str, descriptor: dict[str, object]) -> object:
        """Return one matching admitted response or suspend with its canonical request."""
        self._validate_request_phase(kind)
        if kind == "approval" or kind.startswith("auth:"):
            if self._authorization_requested:
                raise ValueError("Action can request authorization only once")
            self._authorization_requested = True
        if self._index >= MAX_REQUESTS:
            raise ValueError("Action exceeded its human request limit")
        request = {"kind": kind, "ordinal": self._index, **descriptor}
        error = request_error(request, self._catalog)
        if error is not None:
            raise ValueError(f"Action human request is invalid: {error}")
        digest = _fingerprint(request)
        framed = {**request, "fingerprint": digest}
        if self._index == len(self._responses):
            raise HumanRequestSuspension(framed)
        response = self._responses[self._index]
        _match_response(response, kind, self._index, digest)
        value = response["value"]
        _validate_value(kind, descriptor, value)
        self._index += 1
        if kind == "approval" or kind.startswith("auth:"):
            self._authorized = True
        return value

    def resolve_stored_inputs(self, requests: Sequence[tuple[str, dict[str, object]]]) -> None:
        """Return once Team holds every requested Stored Input, or suspend for the first one it does not hold yet.

        Team seals the person's answer and the replay learns only that it holds the value, never the value (ADR-0106).
        """
        self._validate_request_phase("input:password")
        for stored_input, descriptor in requests:
            if stored_input not in self._stored_inputs:
                self._suspend_for_stored_input(descriptor)
        self._resolved_stored_inputs.update(stored_input for stored_input, _descriptor in requests)

    def _suspend_for_stored_input(self, descriptor: dict[str, object]) -> None:
        if self._index >= MAX_REQUESTS:
            raise ValueError("Action exceeded its human request limit")
        if self._index < len(self._responses):
            # Team never answers a Stored Input request with a replay response.
            raise ValueError("Action human response transcript diverged")
        request = {"kind": "input:password", "ordinal": self._index, **descriptor}
        error = request_error(request, self._catalog)
        if error is not None:
            raise ValueError(f"Action human request is invalid: {error}")
        raise HumanRequestSuspension({**request, "fingerprint": _fingerprint(request)})

    def reject_stored_input(self, stored_input: str) -> None:
        """Terminate with an exact rejection only after resolving that slot."""
        if stored_input not in self._resolved_stored_inputs:
            raise ValueError("Action can reject only a resolved Stored Input")
        raise StoredInputRejection(stored_input)

    def _validate_request_phase(self, kind: str) -> None:
        if kind not in self._allowed:
            raise ValueError("Action human request capability is undeclared")
        if self._called:
            raise ValueError("Action cannot request human input after a provider call")

    def finish(self) -> None:
        """Reject an unused response."""
        if self._index != len(self._responses):
            raise ValueError("Action human response transcript diverged")


def _fingerprint(request: object) -> str:
    try:
        return fingerprint(request)
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("Action human request is invalid") from error


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

