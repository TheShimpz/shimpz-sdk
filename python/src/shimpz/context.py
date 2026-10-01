"""Invocation-scoped capabilities passed to an Action."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from ._human import HumanRequestRuntime
from ._reference import index_catalog
from ._request import copy_descriptor, input_descriptor, valid_id
from .human import InputRequest
from .message import Text

Authentication = Literal["password", "totp", "passkey"]
_MAX_SECRET = 16_384
_MAX_SECRETS = 64
# The canonical lowercase text of a random RFC 9562 version 4 UUID, exactly as Team mints it.
_OPERATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def valid_operation_id(value: object) -> bool:
    """Return whether ``value`` is one canonical logical operation id."""
    return isinstance(value, str) and _OPERATION_ID.fullmatch(value) is not None


class OAuthIntegration:
    """One invocation-scoped OAuth bearer token."""

    __slots__ = ("__access_token", "__observe")

    def __init__(self, access_token: str, observe: Callable[[], None]) -> None:
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("OAuth access token is invalid")
        self.__access_token = access_token
        self.__observe = observe

    @property
    def access_token(self) -> str:
        """Return the injected bearer token and close the human-request phase."""
        self.__observe()
        return self.__access_token

    def __repr__(self) -> str:
        return "OAuthIntegration(access_token=<redacted>)"


class Integrations:
    """Read-only OAuth integrations addressable by manifest id."""

    __slots__ = ("__values",)

    def __init__(self, tokens: Mapping[str, str], observe: Callable[[], None] | None = None) -> None:
        observer = _ignore_observation if observe is None else observe
        values = {key: OAuthIntegration(token, observer) for key, token in tokens.items()}
        self.__values = MappingProxyType(values)

    def __getattr__(self, integration_id: str) -> OAuthIntegration:
        try:
            return self.__values[integration_id]
        except KeyError as error:
            raise AttributeError(f"integration {integration_id!r} was not injected") from error

    def __getitem__(self, integration_id: str) -> OAuthIntegration:
        try:
            return self.__values[integration_id]
        except KeyError as error:
            raise KeyError(f"integration {integration_id!r} was not injected") from error

    def __repr__(self) -> str:
        return f"Integrations(ids={tuple(self.__values)})"


@dataclass(frozen=True, slots=True)
class ActionDeclaration:
    """The reviewed contract facts one invocation enforces: request capabilities, Stored Inputs, and catalog."""

    human_requests: Sequence[str] = ()
    stored_inputs: Sequence[str] = ()
    messages: Sequence[Mapping[str, object]] = ()


class Context:
    """Trusted integrations and attributable human requests for one invocation."""

    __slots__ = ("_catalog", "_human", "_operation_id", "_secrets", "_stored_input_ids", "integrations")

    def __init__(
        self,
        integration_tokens: Mapping[str, str],
        declaration: ActionDeclaration | None = None,
        responses: Sequence[Mapping[str, object]] = (),
        *,
        stored_inputs: Mapping[str, str] | None = None,
        operation_id: str | None = None,
    ) -> None:
        reviewed = ActionDeclaration() if declaration is None else declaration
        declared = tuple(reviewed.stored_inputs)
        values = dict(stored_inputs or {})
        if (
            len(declared) > 1
            or len(declared) != len(set(declared))
            or any(not valid_id(stored_input) for stored_input in declared)
            or set(values) - set(declared)
            or len(values) > 1
            or any(not isinstance(value, str) or not 1 <= len(value) <= 1024 for value in values.values())
        ):
            raise ValueError("Action Stored Input invocation is invalid")
        if operation_id is not None and not valid_operation_id(operation_id):
            raise ValueError("Action operation_id is invalid")
        self._operation_id = operation_id
        self._secrets: list[str] = []
        self._stored_input_ids = frozenset(declared)
        self._catalog = index_catalog(reviewed.messages)
        self._human = HumanRequestRuntime(reviewed.human_requests, responses, values, self._catalog)
        self.integrations = Integrations(integration_tokens, self._human.observe_token)

    @property
    def operation_id(self) -> str:
        """Return the stable logical operation id Team assigned to this invocation.

        The value repeats on every replay and permitted retry of the same operation and changes for a new run, so an
        Action may send it as a provider idempotency key within that provider's documented key rules.
        """
        if self._operation_id is None:
            raise RuntimeError("Action operation_id exists only during a Team invocation")
        return self._operation_id

    def register_secret(self, value: str) -> None:
        """Protect one secret the Action derived or acquired, so no failure diagnostic can disclose it.

        Integration tokens, Stored Input values, and password responses are already protected.
        """
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

    def request_input(self, request: InputRequest) -> str | list[str]:
        """Pause for one closed, specialized input field."""
        if not isinstance(request, InputRequest):
            raise TypeError("Action input request is invalid")
        capability = f"input:{request.kind}"
        descriptor = input_descriptor(request, self._catalog)
        if request.stored_input is None:
            value = self._human.resolve(capability, descriptor)
        else:
            if request.stored_input not in self._stored_input_ids:
                raise ValueError("Action Stored Input is undeclared")
            value = self._human.resolve_stored_input(request.stored_input, descriptor)
        if not isinstance(value, str | list):
            raise ValueError("Action human input response is invalid")
        return value

    def reject_stored_input(self, stored_input: str) -> None:
        """Reject one exact Stored Input resolved by this invocation."""
        if stored_input not in self._stored_input_ids:
            raise ValueError("Action Stored Input is undeclared")
        self._human.reject_stored_input(stored_input)

    def _finish(self, result: object) -> None:
        self._human.finish(result)


def _ignore_observation() -> None:
    pass
