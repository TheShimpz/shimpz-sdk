"""Build canonical human-request descriptors whose copy references the reviewed catalog."""

from __future__ import annotations

from collections.abc import Sequence

from ._reference import Catalog, copy_reference
from .human import InputOption, InputRequest

_LENGTH_LIMITS = {"text": 4096, "textarea": 16000, "password": 1024, "phone": 64}
_CHOICE_KINDS = {"select", "choice", "choices"}


def copy_descriptor(title: object, description: object, catalog: Catalog) -> dict[str, object]:
    """Return the title and description references shared by every request kind."""
    return {
        "title": copy_reference(title, "title", catalog),
        "description": copy_reference(description, "description", catalog),
    }


def input_descriptor(request: InputRequest, catalog: Catalog) -> dict[str, object]:
    """Return the canonical descriptor of one closed input request."""
    kind = request.kind
    if kind not in {*_LENGTH_LIMITS, *_CHOICE_KINDS}:
        raise ValueError("Action input kind is invalid")
    if type(request.required) is not bool:
        raise ValueError("Action input required flag is invalid")
    if request.stored_input is not None and (kind != "password" or not valid_id(request.stored_input)):
        raise ValueError("Action Stored Input request is invalid")
    base = {
        **copy_descriptor(request.title, request.description, catalog),
        "label": copy_reference(request.label, "label", catalog),
        "required": request.required,
    }
    if kind in _CHOICE_KINDS:
        return _choice_descriptor(request, base, catalog)
    if request.options:
        raise ValueError("Action input options are invalid")
    maximum = _LENGTH_LIMITS[kind] if request.max_length is None else request.max_length
    valid_bounds = (
        type(request.min_length) is int
        and type(maximum) is int
        and 0 <= request.min_length <= maximum <= _LENGTH_LIMITS[kind]
    )
    if not valid_bounds:
        raise ValueError("Action input length bounds are invalid")
    hint = copy_reference(request.placeholder, "placeholder", catalog, nullable=True)
    descriptor = {**base, "placeholder": hint, "min_length": request.min_length, "max_length": maximum}
    if request.stored_input is not None:
        descriptor["stored_input"] = request.stored_input
    return descriptor


def _choice_descriptor(request: InputRequest, base: dict[str, object], catalog: Catalog) -> dict[str, object]:
    choices = _option_payload(request.options, catalog)
    if request.kind != "choices":
        return {**base, "options": choices}
    minimum = max(1, request.min_selections) if request.required else request.min_selections
    maximum = len(choices) if request.max_selections is None else request.max_selections
    if not 0 <= minimum <= maximum <= len(choices):
        raise ValueError("Action input selection bounds are invalid")
    return {**base, "options": choices, "min_selections": minimum, "max_selections": maximum}


def _option_payload(options: Sequence[InputOption], catalog: Catalog) -> list[dict[str, object]]:
    if not 2 <= len(options) <= 32 or any(not isinstance(item, InputOption) for item in options):
        raise ValueError("Action input options are invalid")
    values: set[str] = set()
    payload: list[dict[str, object]] = []
    for option in options:
        value = _option_value(option.value)
        if value in values:
            raise ValueError("Action input options are invalid")
        values.add(value)
        payload.append(
            {
                "value": value,
                "label": copy_reference(option.label, "option_label", catalog),
                "description": copy_reference(option.description, "option_description", catalog, nullable=True),
            }
        )
    return payload


def _option_value(value: object) -> str:
    invalid = (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > 128
        or not value.isprintable()
    )
    if invalid:
        raise ValueError("Action input option value is invalid")
    return value  # type: ignore[return-value]


def valid_id(value: object) -> bool:
    """Return whether a value is a lowercase dash-separated protocol id."""
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
