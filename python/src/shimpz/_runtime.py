"""Validated in-process Power execution used by the Shimpz CLI."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Mapping
from typing import Any

from . import _native
from ._project import AssistantProject, PowerDefinition
from .context import Context

_MAX_VALUE_BYTES = 512 * 1_024


class PowerExecutionError(RuntimeError):
    """A Power failed without exposing its input or account secrets."""


async def invoke_power(
    project: AssistantProject,
    power_id: str,
    inputs: Mapping[str, object],
    account_tokens: Mapping[str, str] | None = None,
) -> object:
    """Validate and invoke one discovered Power."""
    definition = _find_power(project, power_id)
    tokens = dict(account_tokens or {})
    if set(tokens) != set(definition.accounts):
        message = "Power accounts do not match its declaration"
        raise ValueError(message)
    input_value = dict(inputs)
    _validate_value(definition.input_schema, input_value, "Power input")
    context = Context(tokens)
    arguments = dict(input_value)
    if "ctx" in inspect.signature(definition.body).parameters:
        arguments["ctx"] = context
    result = (await asyncio.gather(definition.body(**arguments), return_exceptions=True))[0]
    if isinstance(result, BaseException):
        message = "Power execution failed"
        raise PowerExecutionError(message) from None
    _validate_value(definition.output_schema, result, "Power result")
    return result


def _find_power(project: AssistantProject, power_id: str) -> PowerDefinition:
    for definition in project.powers:
        if definition.id == power_id:
            return definition
    message = "Power id does not exist"
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
