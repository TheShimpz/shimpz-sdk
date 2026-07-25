"""Compile Power type annotations into the supported JSON Schema subset."""

from __future__ import annotations

import inspect
import re
from typing import Annotated, Literal, NotRequired, Required, get_args, get_origin, get_type_hints, is_typeddict

type JsonSchema = dict[str, object]

_PRIMITIVES: dict[object, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}
_CONSTRAINT_TYPES: dict[str, type | tuple[type, ...]] = {
    "minimum": (int, float),
    "maximum": (int, float),
    "minLength": int,
    "maxLength": int,
    "pattern": str,
    "minItems": int,
    "maxItems": int,
    "uniqueItems": bool,
}
_ALLOWED_CONSTRAINTS = {
    "string": {"minLength", "maxLength", "pattern"},
    "integer": {"minimum", "maximum"},
    "number": {"minimum", "maximum"},
    "array": {"minItems", "maxItems", "uniqueItems"},
}


def compile_power_schemas(body: object) -> tuple[JsonSchema, JsonSchema]:
    """Compile one Power signature into closed input and output schemas."""
    if not callable(body):
        message = "Power body is not callable"
        raise TypeError(message)
    signature = inspect.signature(body)
    hints = get_type_hints(body, include_extras=True)
    properties: dict[str, object] = {}
    for name, parameter in signature.parameters.items():
        if name == "ctx":
            _validate_context(parameter)
            continue
        _validate_parameter(name, parameter, hints)
        properties[name] = schema_for_type(hints[name])
    return_annotation = hints.get("return", inspect.Signature.empty)
    if return_annotation is inspect.Signature.empty:
        message = "Power return type annotation is required"
        raise TypeError(message)
    return _object_schema(properties), _output_schema(return_annotation)


def schema_for_type(annotation: object) -> JsonSchema:
    """Compile one supported Python annotation."""
    origin = get_origin(annotation)
    if origin is Annotated:
        base, *metadata = get_args(annotation)
        schema = schema_for_type(base)
        _apply_metadata(schema, metadata)
        return schema
    if origin in {Required, NotRequired}:
        return schema_for_type(get_args(annotation)[0])
    primitive = _PRIMITIVES.get(annotation)
    if primitive is not None:
        return {"type": primitive}
    if origin is Literal:
        return _literal_schema(get_args(annotation))
    if origin is list:
        arguments = get_args(annotation)
        if len(arguments) != 1:
            message = "list annotations require one item type"
            raise TypeError(message)
        return {"type": "array", "items": schema_for_type(arguments[0])}
    if is_typeddict(annotation):
        return _typed_dict_schema(annotation)
    message = "unsupported Power type annotation"
    raise TypeError(message)


def _validate_parameter(
    name: str,
    parameter: inspect.Parameter,
    hints: dict[str, object],
) -> None:
    if parameter.kind not in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}:
        message = "Power parameters cannot use positional-only, *args, or **kwargs"
        raise TypeError(message)
    if parameter.default is not inspect.Signature.empty:
        message = "Power parameters cannot have default values"
        raise TypeError(message)
    if name not in hints:
        message = f"Power parameter {name} requires a type annotation"
        raise TypeError(message)


def _validate_context(parameter: inspect.Parameter) -> None:
    valid = parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is inspect.Signature.empty
    if not valid:
        message = "ctx must be keyword-only without a default"
        raise TypeError(message)


def _output_schema(annotation: object) -> JsonSchema:
    schema = schema_for_type(annotation)
    if schema.get("type") != "object":
        message = "Power return type must be a TypedDict"
        raise TypeError(message)
    return schema


def _typed_dict_schema(annotation: object) -> JsonSchema:
    hints = get_type_hints(annotation, include_extras=True)
    required = set(getattr(annotation, "__required_keys__", hints))
    optional = set(getattr(annotation, "__optional_keys__", ()))
    if required | optional != set(hints):
        message = "TypedDict keys are invalid"
        raise TypeError(message)
    properties = {name: schema_for_type(value) for name, value in hints.items()}
    schema = _object_schema(properties)
    schema["required"] = [name for name in hints if name in required]
    return schema


def _object_schema(properties: dict[str, object]) -> JsonSchema:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _literal_schema(options: tuple[object, ...]) -> JsonSchema:
    valid = (
        bool(options)
        and all(isinstance(option, str) and bool(option) for option in options)
        and len(set(options)) == len(options)
    )
    if not valid:
        message = "Literal annotations require unique non-empty strings"
        raise TypeError(message)
    return {"type": "string", "enum": list(options)}


def _apply_metadata(schema: JsonSchema, metadata: list[object]) -> None:
    constraints: dict[str, object] = {}
    for item in metadata:
        if isinstance(item, str):
            _add_description(schema, item)
        elif isinstance(item, dict):
            _add_constraints(constraints, item)
        else:
            message = "Annotated metadata must be a description or constraints dictionary"
            raise TypeError(message)
    _validate_constraints(schema, constraints)
    schema.update(constraints)


def _add_description(schema: JsonSchema, description: str) -> None:
    if "description" in schema or not description.strip() or len(description) > 4_096:
        message = "Annotated description is invalid"
        raise TypeError(message)
    schema["description"] = description


def _add_constraints(target: dict[str, object], values: dict[object, object]) -> None:
    for key, value in values.items():
        expected = _CONSTRAINT_TYPES.get(key) if isinstance(key, str) else None
        invalid_number = isinstance(value, bool) and expected is not bool
        if expected is None or invalid_number or not isinstance(value, expected) or key in target:
            message = "Annotated constraints are invalid"
            raise TypeError(message)
        target[key] = value


def _validate_constraints(schema: JsonSchema, constraints: dict[str, object]) -> None:
    allowed = _ALLOWED_CONSTRAINTS.get(schema.get("type"), set())
    if set(constraints) - allowed:
        message = "Annotated constraints do not match the declared type"
        raise TypeError(message)
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in constraints and constraints[key] < 0:
            message = "Annotated bounds must be non-negative"
            raise TypeError(message)
    for minimum, maximum in (
        ("minimum", "maximum"),
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
    ):
        if minimum in constraints and maximum in constraints and constraints[minimum] > constraints[maximum]:
            message = "Annotated bounds are inconsistent"
            raise TypeError(message)
    pattern = constraints.get("pattern")
    if isinstance(pattern, str):
        try:
            re.compile(pattern)
        except re.error as error:
            message = "Annotated pattern is invalid"
            raise TypeError(message) from error
