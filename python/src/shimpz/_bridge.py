"""Private subprocess bridge used by the Rust CLI."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from ._human import HumanRequestSuspension, StoredInputRejection
from ._json import strict_loads
from ._language_pack import read_pack, verify_pack
from ._project import AssistantProject, load_catalog_document
from ._reference import render_request
from ._runtime import ActionFailure, ActionInvocation, invoke_action
from .context import valid_operation_id

_MAX_REQUEST_BYTES = 512 * 1_024


def main(arguments: list[str] | None = None) -> int:
    """Run one bounded CLI-to-SDK request."""
    args = sys.argv[1:] if arguments is None else arguments
    try:
        output = dispatch(args, sys.stdin)
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        sys.stderr.write(f"shimpz: {error}\n")
        return 1
    except SystemExit, KeyboardInterrupt:
        sys.stderr.write("shimpz: aborted\n")
        return 1
    sys.stdout.write(output)
    sys.stdout.write("\n")
    return 0


def dispatch(arguments: list[str], source: TextIO) -> str:
    """Dispatch one private bridge command and return JSON."""
    if len(arguments) == 3 and arguments[0] == "invoke":
        return _invoke(Path(arguments[1]), arguments[2], source)
    command = _PROJECT_COMMANDS.get(arguments[0]) if len(arguments) == 2 else None
    if command is None:
        message = "private bridge command is invalid"
        raise ValueError(message)
    return command(Path(arguments[1]), source)


def _invoke(root: Path, action_id: str, source: TextIO) -> str:
    project = AssistantProject.load(root)
    payload = _request(source)
    try:
        result = asyncio.run(
            invoke_action(
                project,
                action_id,
                ActionInvocation(
                    inputs=payload["input"],
                    integrations=payload["integrations"],
                    stored_inputs=payload["stored_inputs"],
                    operation_id=payload["operation_id"],
                    responses=tuple(payload.get("responses", ())),
                ),
            )
        )
    except HumanRequestSuspension as suspension:
        return _json({"type": "request", "request": suspension.request})
    except StoredInputRejection as rejection:
        return _json({"type": "stored_input_rejected", "stored_input": rejection.stored_input})
    except ActionFailure as failure:
        return _json(failure.envelope)
    return _json({"type": "result", "result": result})


def _render(root: Path, source: TextIO) -> dict[str, Any]:
    """Render one framed request in English for local display; the canonical request is unchanged."""
    payload = _bounded_json(source)
    if not isinstance(payload, dict) or set(payload) != {"request"} or not isinstance(payload["request"], dict):
        message = "private bridge request is invalid"
        raise ValueError(message)
    try:
        return render_request(payload["request"], load_catalog_document(root)["messages"])
    except (KeyError, TypeError) as error:
        message = "Action human request is invalid"
        raise ValueError(message) from error


_PROJECT_COMMANDS: dict[str, Callable[[Path, TextIO], str]] = {
    "contract": lambda root, _: AssistantProject.load(root).contract(),
    "catalog": lambda root, _: _json(load_catalog_document(root)),
    "render": lambda root, source: _json(_render(root, source)),
    "verify-pack": lambda root, source: _json(verify_pack(root, read_pack(_binary(source)))),
}


def _binary(source: TextIO) -> BinaryIO:
    """Return the byte stream under a text source, so pack bytes are read exactly."""
    buffer = getattr(source, "buffer", None)
    if buffer is None:
        message = "private bridge request is invalid"
        raise ValueError(message)
    return buffer


def _bounded_json(source: TextIO) -> object:
    raw = source.read(_MAX_REQUEST_BYTES + 1)
    if not 0 < len(raw.encode()) <= _MAX_REQUEST_BYTES:
        message = "private bridge request is invalid"
        raise ValueError(message)
    try:
        return strict_loads(raw)
    except ValueError as error:
        message = "private bridge request is invalid"
        raise ValueError(message) from error


def _request(source: TextIO) -> dict[str, Any]:
    payload = _bounded_json(source)
    valid = (
        isinstance(payload, dict)
        and set(payload)
        in (
            {"input", "integrations", "stored_inputs", "operation_id"},
            {"input", "integrations", "stored_inputs", "operation_id", "responses"},
        )
        and valid_operation_id(payload["operation_id"])
        and isinstance(payload["input"], dict)
        and isinstance(payload["integrations"], dict)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in payload["integrations"].items())
        and _valid_stored_inputs(payload["stored_inputs"])
        and (
            "responses" not in payload
            or (
                isinstance(payload["responses"], list)
                and len(payload["responses"]) <= 8
                and all(isinstance(item, dict) for item in payload["responses"])
            )
        )
    )
    if not valid:
        message = "private bridge request is invalid"
        raise ValueError(message)
    return payload


def _valid_stored_inputs(value: object) -> bool:
    return (
        isinstance(value, dict)
        and len(value) <= 1
        and all(
            isinstance(key, str) and isinstance(item, str) and 1 <= len(item) <= 1024 for key, item in value.items()
        )
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    raise SystemExit(main())
