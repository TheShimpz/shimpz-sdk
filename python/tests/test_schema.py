"""Tests for annotation-first Power schemas."""

from typing import Annotated, Literal, NotRequired, TypedDict

import pytest
from shimpz._schema import compile_power_schemas, schema_for_type


class DnsRecord(TypedDict):
    id: str
    proxied: bool
    note: NotRequired[str]


def test_compiles_annotations_without_field_declarations() -> None:
    async def run(
        zone: Annotated[str, "DNS zone", {"minLength": 1}],
        record_type: Literal["A", "AAAA"],
        tags: list[str],
    ) -> DnsRecord:
        raise NotImplementedError

    input_schema, output_schema = compile_power_schemas(run)

    assert input_schema == {
        "type": "object",
        "properties": {
            "zone": {"type": "string", "description": "DNS zone", "minLength": 1},
            "record_type": {"type": "string", "enum": ["A", "AAAA"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["zone", "record_type", "tags"],
        "additionalProperties": False,
    }
    assert output_schema["required"] == ["id", "proxied"]
    assert output_schema["additionalProperties"] is False


def test_excludes_the_reserved_context_parameter() -> None:
    async def run(zone: str, *, ctx: object) -> DnsRecord:
        raise NotImplementedError

    input_schema, _ = compile_power_schemas(run)

    assert input_schema["required"] == ["zone"]


@pytest.mark.parametrize(
    "annotation",
    [
        str | None,
        tuple[str],
        dict[str, str],
        Literal[1, 2],
    ],
)
def test_rejects_unsupported_annotations(annotation: object) -> None:
    with pytest.raises(TypeError):
        schema_for_type(annotation)


def test_rejects_parameter_defaults() -> None:
    async def run(zone: str = "example.com") -> DnsRecord:
        raise NotImplementedError

    with pytest.raises(TypeError, match="default"):
        compile_power_schemas(run)


def test_requires_a_typed_dict_output() -> None:
    async def run(zone: str) -> str:
        return zone

    with pytest.raises(TypeError, match="TypedDict"):
        compile_power_schemas(run)


def test_rejects_invalid_constraints() -> None:
    with pytest.raises(TypeError, match="do not match"):
        schema_for_type(Annotated[str, {"minimum": 1}])
