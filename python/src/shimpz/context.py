"""Invocation-scoped capabilities passed to an Action."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Literal

from ._human import HumanRequestRuntime
from .human import InputOption, InputRequest

Authentication = Literal["password", "totp", "passkey"]


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


class Context:
    """Trusted integrations and attributable human requests for one invocation."""

    __slots__ = ("_human", "_stored_input_ids", "integrations")

    def __init__(
        self,
        integration_tokens: Mapping[str, str],
        human_requests: Sequence[str] = (),
        responses: Sequence[Mapping[str, object]] = (),
        *,
        stored_input_ids: Sequence[str] = (),
        stored_inputs: Mapping[str, str] | None = None,
    ) -> None:
        declared = tuple(stored_input_ids)
        values = dict(stored_inputs or {})
        if (
            len(declared) > 1
            or len(declared) != len(set(declared))
            or any(not _valid_id(stored_input) for stored_input in declared)
            or set(values) - set(declared)
            or len(values) > 1
            or any(not isinstance(value, str) or not 1 <= len(value) <= 1024 for value in values.values())
        ):
            raise ValueError("Action Stored Input invocation is invalid")
        self._stored_input_ids = frozenset(declared)
        self._human = HumanRequestRuntime(human_requests, responses, values)
        self.integrations = Integrations(integration_tokens, self._human.observe_token)

    def request_approval(self, *, title: str, description: str) -> None:
        """Pause until the Team's authenticated human approves the described action."""
        descriptor = _copy(title, description)
        self._human.resolve("approval", descriptor)

    def request_auth(self, authentication: Authentication, *, title: str, description: str) -> None:
        """Authorize through one platform-side mechanism without receiving its material."""
        if authentication not in {"password", "totp", "passkey"}:
            raise ValueError("Action authentication mechanism is invalid")
        descriptor = _copy(title, description)
        self._human.resolve(f"auth:{authentication}", descriptor)

    def request_input(self, request: InputRequest) -> str | list[str]:
        """Pause for one closed, specialized input field."""
        if not isinstance(request, InputRequest):
            raise TypeError("Action input request is invalid")
        capability = f"input:{request.kind}"
        descriptor = _input_descriptor(request)
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


def _public_text(value: object, maximum: int, label: str) -> str:
    invalid = (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > maximum
        or not value.isprintable()
    )
    if invalid:
        raise ValueError(f"{label} is invalid")
    return value


def _copy(title: object, description: object) -> dict[str, object]:
    return {
        "title": _public_text(title, 80, "Action request title"),
        "description": _public_text(description, 500, "Action request description"),
    }


def _option_payload(options: Sequence[InputOption]) -> list[dict[str, object]]:
    if not 2 <= len(options) <= 32 or any(not isinstance(item, InputOption) for item in options):
        raise ValueError("Action input options are invalid")
    values: set[str] = set()
    payload: list[dict[str, object]] = []
    for option in options:
        value = _public_text(option.value, 128, "Action input option value")
        if value in values:
            raise ValueError("Action input options are invalid")
        values.add(value)
        description = (
            None
            if option.description is None
            else _public_text(option.description, 160, "Action input option description")
        )
        payload.append(
            {
                "value": value,
                "label": _public_text(option.label, 80, "Action input option label"),
                "description": description,
            }
        )
    return payload


def _input_descriptor(request: InputRequest) -> dict[str, object]:
    kind = request.kind
    if kind not in {"text", "textarea", "password", "phone", "select", "choice", "choices"}:
        raise ValueError("Action input kind is invalid")
    if type(request.required) is not bool:
        raise ValueError("Action input required flag is invalid")
    if request.stored_input is not None and (kind != "password" or not _valid_id(request.stored_input)):
        raise ValueError("Action Stored Input request is invalid")
    base = {
        **_copy(request.title, request.description),
        "label": _public_text(request.label, 80, "Action input label"),
        "required": request.required,
    }
    if kind in {"select", "choice", "choices"}:
        choices = _option_payload(request.options)
        if kind != "choices":
            return {**base, "options": choices}
        minimum = max(1, request.min_selections) if request.required else request.min_selections
        maximum = len(choices) if request.max_selections is None else request.max_selections
        if not 0 <= minimum <= maximum <= len(choices):
            raise ValueError("Action input selection bounds are invalid")
        return {**base, "options": choices, "min_selections": minimum, "max_selections": maximum}
    if request.options:
        raise ValueError("Action input options are invalid")
    limits = {"text": 4096, "textarea": 16000, "password": 1024, "phone": 64}
    maximum = limits[kind] if request.max_length is None else request.max_length
    valid_bounds = (
        type(request.min_length) is int and type(maximum) is int and 0 <= request.min_length <= maximum <= limits[kind]
    )
    if not valid_bounds:
        raise ValueError("Action input length bounds are invalid")
    hint = None if request.placeholder is None else _public_text(request.placeholder, 120, "Action input placeholder")
    descriptor = {**base, "placeholder": hint, "min_length": request.min_length, "max_length": maximum}
    if request.stored_input is not None:
        descriptor["stored_input"] = request.stored_input
    return descriptor


def _ignore_observation() -> None:
    pass


def _valid_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value[0].isascii()
        and value[0].islower()
        and all(
            character.isascii() and (character.islower() or character.isdigit() or character == "-")
            for character in value
        )
        and not value.endswith("-")
        and "--" not in value
    )
