"""Validated in-process Action execution used by the Shimpz CLI."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import sys
from collections.abc import Mapping
from typing import Any

from . import _native
from ._human import HumanRequestSuspension
from ._project import ActionDefinition, AssistantProject
from .context import Context

_MAX_VALUE_BYTES = 512 * 1_024


class ActionExecutionError(RuntimeError):
    """An Action failed without exposing its input or integration secrets."""


async def invoke_action(
    project: AssistantProject,
    action_id: str,
    inputs: Mapping[str, object],
    integration_tokens: Mapping[str, str] | None = None,
    responses: tuple[Mapping[str, object], ...] = (),
) -> object:
    """Validate and invoke one discovered Action."""
    definition = _find_action(project, action_id)
    tokens = dict(integration_tokens or {})
    if set(tokens) != set(definition.integrations):
        message = "Action integrations do not match its declaration"
        raise ValueError(message)
    input_value = dict(inputs)
    _validate_value(definition.input_schema, input_value, "Action input")
    context = Context(tokens, definition.human_requests, responses)
    arguments = dict(input_value)
    if "ctx" in inspect.signature(definition.body).parameters:
        arguments["ctx"] = context
    with contextlib.redirect_stdout(sys.stderr):
        try:
            result = (await asyncio.gather(definition.body(**arguments), return_exceptions=True))[0]
        except (SystemExit, KeyboardInterrupt) as error:
            result = error
    if isinstance(result, BaseException):
        if isinstance(result, HumanRequestSuspension):
            raise result
        message = "Action execution failed"
        raise ActionExecutionError(message) from None
    context._finish(result)
    _validate_value(definition.output_schema, result, "Action result")
    return result


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
