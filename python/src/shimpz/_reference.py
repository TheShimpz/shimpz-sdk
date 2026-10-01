"""Turn Action copy into catalog references and render references through the English catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ._protocol.human_request_validator import COPY_BOUNDS, reference_error
from ._protocol.message_catalog_validator import message_id, public_text, render
from .message import Text

Catalog = Mapping[str, Mapping[str, object]]
_LABELS = {
    "title": "title",
    "description": "description",
    "label": "label",
    "placeholder": "placeholder",
    "option_label": "option label",
    "option_description": "option description",
}


def index_catalog(messages: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Return the reviewed catalog keyed by message id."""
    catalog = {str(message["id"]): dict(message) for message in messages}
    if len(catalog) != len(messages):
        raise ValueError("Action message catalog is invalid")
    return catalog


def copy_reference(copy: object, field: str, catalog: Catalog, *, nullable: bool = False) -> dict[str, object] | None:
    """Return the catalog reference for one request copy field, validated like Team admission."""
    label = f"Action request {_LABELS[field]}"
    if copy is None and nullable:
        return None
    if not isinstance(copy, Text):
        raise TypeError(f"{label} must be shimpz.text(...) catalog copy, not {type(copy).__name__}")
    identifier = message_id(copy.template)
    message = catalog.get(identifier)
    if message is None:
        raise ValueError(f"{label} is not a declared catalog message; write it as a literal shimpz.text() call")
    declared = {item["name"]: (item["kind"], item["max_length"]) for item in message["params"]}  # type: ignore[attr-defined]
    supplied = {name: (param.kind, param.max_length) for name, param in copy.params}
    if supplied != declared:
        raise ValueError(f"{label} parameters do not match the catalog declaration")
    reference = {"message": identifier, "params": {name: param.value for name, param in copy.params}}
    error = reference_error(reference, catalog, COPY_BOUNDS[field])
    if error is not None:
        raise ValueError(f"{label} is invalid: {error}")
    return reference


def render_reference(reference: Mapping[str, object], field: str, catalog: Catalog) -> str:
    """Render one admitted reference through the English catalog and check the field bound after insertion."""
    bound = COPY_BOUNDS[field]
    error = reference_error(reference, catalog, bound)
    if error is not None:
        raise ValueError(f"Action request {_LABELS[field]} is invalid: {error}")
    rendered = render(reference, str(catalog[str(reference["message"])]["msgid"]))
    if not public_text(rendered, bound):
        raise ValueError(f"Action request {_LABELS[field]} does not render within its field")
    return rendered
