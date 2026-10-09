"""Invocation-scoped capabilities passed to an Action."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ._human import HumanRequestRuntime
from ._reference import index_catalog
from ._request import copy_descriptor, input_descriptor, valid_id
from .fetch import Headers, ProviderChannel, Response, request_frame
from .human import InputRequest
from .message import Text

Authentication = Literal["password", "totp", "passkey"]
_MAX_SECRET = 16_384
_MAX_SECRETS = 64
# The most Stored Inputs one Action may use: every one its manifest can declare.
_MAX_STORED_INPUTS = 8
# The canonical lowercase text of a random RFC 9562 version 4 UUID, exactly as Team mints it.
_OPERATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def valid_operation_id(value: object) -> bool:
    """Return whether ``value`` is one canonical logical operation id."""
    return isinstance(value, str) and _OPERATION_ID.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class ActionDeclaration:
    """The reviewed contract facts one invocation enforces: request capabilities, Stored Inputs, and catalog."""

    human_requests: Sequence[str] = ()
    stored_inputs: Sequence[str] = ()
    messages: Sequence[Mapping[str, object]] = ()


class Context:
    """Team-made provider calls and attributable human requests for one invocation."""

    __slots__ = ("_catalog", "_channel", "_human", "_operation_id", "_secrets", "_stored_input_ids")

    def __init__(
        self,
        declaration: ActionDeclaration | None = None,
        responses: Sequence[Mapping[str, object]] = (),
        *,
        stored_inputs: Iterable[str] = (),
        operation_id: str | None = None,
        channel: ProviderChannel | None = None,
    ) -> None:
        reviewed = ActionDeclaration() if declaration is None else declaration
        declared = tuple(reviewed.stored_inputs)
        held = frozenset(stored_inputs)
        if (
            len(declared) > _MAX_STORED_INPUTS
            or len(declared) != len(set(declared))
            or any(not valid_id(stored_input) for stored_input in declared)
            or held - set(declared)
        ):
            raise ValueError("Action Stored Input invocation is invalid")
        if operation_id is not None and not valid_operation_id(operation_id):
            raise ValueError("Action operation_id is invalid")
        self._operation_id = operation_id
        self._channel = channel
        self._secrets: list[str] = []
        self._stored_input_ids = frozenset(declared)
        self._catalog = index_catalog(reviewed.messages)
        self._human = HumanRequestRuntime(reviewed.human_requests, responses, held, self._catalog)

    @property
    def operation_id(self) -> str:
        """Return the stable logical operation id Team assigned to this invocation.

        The value repeats on every replay and permitted retry of the same operation and changes for a new run, so an
        Action may send it as a provider idempotency key within that provider's documented key rules.
        """
        if self._operation_id is None:
            raise RuntimeError("Action operation_id exists only during a Team invocation")
        return self._operation_id

    async def fetch(
        self,
        method: str,
        url: str,
        *,
        headers: Headers = (),
        body: bytes | str | None = None,
        timeout_ms: int | None = None,
    ) -> Response:
        """Ask Team to make one HTTPS call to a declared host and return the complete response.

        Team adds every credential this Action declares for that host, so the Action never sends or sees one. The call
        closes the human-request phase. ``timeout_ms`` is at most 30000; the invocation's own deadline always applies.
        Raises ``FetchError`` when Team makes no usable call.
        """
        if self._channel is None:
            raise RuntimeError("Action provider calls exist only during a Team invocation")
        frame = request_frame(method, url, headers, body, timeout_ms)
        self._human.observe_call()
        return self._channel.call(frame)

    def register_secret(self, value: str) -> None:
        """Protect one secret the Action derived or acquired, so no failure diagnostic can disclose it."""
        if not isinstance(value, str) or not 1 <= len(value) <= _MAX_SECRET or len(self._secrets) >= _MAX_SECRETS:
            raise ValueError("Action secret registration is invalid")
        self._secrets.append(value)

    def request_approval(self, *, title: Text, description: Text) -> None:
        """Pause until the Team's authenticated human approves the described action."""
        descriptor = copy_descriptor(title, description, self._catalog)
        self._human.resolve("approval", descriptor)

    def request_auth(self, authentication: Authentication, *, title: Text, description: Text) -> None:
        """Authorize through one platform-side mechanism without receiving its material."""
        if authentication not in {"password", "totp", "passkey"}:
            raise ValueError("Action authentication mechanism is invalid")
        descriptor = copy_descriptor(title, description, self._catalog)
        self._human.resolve(f"auth:{authentication}", descriptor)

    def request_input(self, request: InputRequest) -> str | list[str] | None:
        """Pause for one closed, specialized input field.

        A request naming a Stored Input returns ``None`` once Team holds it, the way ``request_stored_inputs`` does.
        """
        if not isinstance(request, InputRequest):
            raise TypeError("Action input request is invalid")
        if request.stored_input is not None:
            self.request_stored_inputs(request)
            return None
        value = self._human.resolve(f"input:{request.kind}", input_descriptor(request, self._catalog))
        if not isinstance(value, str | list):
            raise ValueError("Action human input response is invalid")
        return value

    def request_stored_inputs(self, *requests: InputRequest) -> None:
        """Return once Team holds every one of several declared Stored Inputs.

        Each request is a password ``InputRequest`` naming a distinct Stored Input this Action declares. Team asks the
        person only for a value it does not keep yet, one request at a time. The values never reach the Action: Team
        places each in the provider calls it makes for this Action (ADR-0106).
        """
        if not requests or not all(isinstance(request, InputRequest) for request in requests):
            raise TypeError("Action Stored Input requests are invalid")
        stored_inputs = [request.stored_input for request in requests]
        if any(stored_input not in self._stored_input_ids for stored_input in stored_inputs):
            raise ValueError("Action Stored Input is undeclared")
        if len(set(stored_inputs)) != len(stored_inputs):
            raise ValueError("Action Stored Input requests must be distinct")
        descriptors = [input_descriptor(request, self._catalog) for request in requests]
        self._human.resolve_stored_inputs(list(zip(stored_inputs, descriptors, strict=True)))

    def reject_stored_input(self, stored_input: str) -> None:
        """Reject one exact Stored Input resolved by this invocation."""
        if stored_input not in self._stored_input_ids:
            raise ValueError("Action Stored Input is undeclared")
        self._human.reject_stored_input(stored_input)

    def _finish(self) -> None:
        self._human.finish()

    def _authorized(self) -> bool:
        return self._human.authorized()
