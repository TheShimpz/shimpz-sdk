"""Validated in-process Action execution used by the Shimpz CLI."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import _native
from ._failure import failure_envelope
from ._files import bind_files
from ._human import HumanRequestSuspension, StoredInputRejection
from ._project import ActionDefinition, AssistantProject
from .context import ActionDeclaration, Context

_MAX_VALUE_BYTES = 512 * 1_024


class _Discard(io.TextIOBase):
    """A non-buffering text sink that keeps nothing an Action writes."""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        return len(text)


_DISCARD = _Discard()


class ActionFailure(Exception):
    """Private control signal carrying one sanitized, bounded failure envelope."""

    def __init__(self, envelope: dict[str, object]) -> None:
        super().__init__("Action failed")
        self.envelope = envelope


@dataclass(frozen=True, slots=True)
class ActionInvocation:
    """One private, bounded invocation passed to an Action process."""

    inputs: Mapping[str, object]
    integrations: Mapping[str, str]
    stored_inputs: Mapping[str, str]
    operation_id: str
    responses: tuple[Mapping[str, object], ...] = ()
    files: Mapping[str, object] = field(default_factory=dict)


async def invoke_action(
    project: AssistantProject,
    action_id: str,
    invocation: ActionInvocation,
) -> object:
    """Validate and invoke one discovered Action."""
    definition = _find_action(project, action_id)
    if not isinstance(invocation, ActionInvocation):
        raise TypeError("Action invocation is invalid")
    tokens = dict(invocation.integrations)
    if set(tokens) != set(definition.integrations):
        message = "Action integrations do not match its declaration"
        raise ValueError(message)
    stored_values = dict(invocation.stored_inputs)
    if set(stored_values) - set(definition.stored_inputs):
        message = "Action Stored Inputs do not match its declaration"
        raise ValueError(message)
    input_value = dict(invocation.inputs)
    _validate_value(definition.input_schema, input_value, "Action input")
    files = _file_arguments(definition, input_value, invocation)
    declaration = ActionDeclaration(
        human_requests=definition.human_requests,
        stored_inputs=definition.stored_inputs,
        messages=project.messages,
    )
    context = Context(
        tokens,
        declaration,
        invocation.responses,
        stored_inputs=stored_values,
        operation_id=invocation.operation_id,
    )
    arguments = {**input_value, **files}
    if "ctx" in inspect.signature(definition.body).parameters:
        arguments["ctx"] = context
    # Ordinary Action output is discarded so it can neither forge the protocol frame nor turn a handled failure into
    # a transport fault. Bytes written past Python's streams, such as native descriptor writes or a handler bound to
    # the original stream before invocation, still reach the process streams and stay transport faults.
    with contextlib.redirect_stdout(_DISCARD), contextlib.redirect_stderr(_DISCARD):
        try:
            result = (await asyncio.gather(definition.body(**arguments), return_exceptions=True))[0]
        except (SystemExit, KeyboardInterrupt) as error:
            result = error
    if isinstance(result, HumanRequestSuspension | StoredInputRejection):
        raise result
    failure = result if isinstance(result, BaseException) else None
    if failure is None:
        try:
            context._finish(result)
            _validate_value(definition.output_schema, result, "Action result")
        except ValueError as error:
            failure = error
    if failure is not None:
        raise ActionFailure(failure_envelope(failure, _secrets(invocation, context))) from None
    return result


def _secrets(invocation: ActionInvocation, context: Context) -> list[str]:
    """Every secret this invocation received or the Action registered, for exact failure redaction."""
    passwords = [
        response["value"]
        for response in invocation.responses
        if response.get("kind") == "input:password" and isinstance(response.get("value"), str)
    ]
    return [*invocation.integrations.values(), *invocation.stored_inputs.values(), *passwords, *context._secrets]


def _file_arguments(
    definition: ActionDefinition, input_value: Mapping[str, object], invocation: ActionInvocation
) -> dict[str, object]:
    """Replace each declared file input id with its validated ``shimpz.File`` before Action code runs."""
    declaration = {
        "input_files": list(definition.input_files),
        "input_schema": definition.input_schema,
        "human_requests": list(definition.human_requests),
    }
    return dict(bind_files(declaration, input_value, invocation.files, invocation.responses))


def _find_action(project: AssistantProject, action_id: str) -> ActionDefinition:
    for definition in project.actions:
        if definition.id == action_id:
            return definition
    message = "Action id does not exist"
    raise ValueError(message)


def _validate_value(schema: dict[str, object], value: object, label: str) -> None:
    try:
        schema_json = _json(schema)
        value_json = _json(value)
        if len(value_json.encode()) > _MAX_VALUE_BYTES:
            raise ValueError
        _native.validate_json(schema_json, value_json)
    except TypeError, ValueError:
        message = f"{label} does not match its annotation"
        raise ValueError(message) from None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
