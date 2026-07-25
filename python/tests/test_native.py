"""Native Genesis boundary tests."""

import json

import pytest
from shimpz import _native

MANIFEST = """
spec = 1
id = "example"
version = "0.1.0"
name = "Example"
summary = "Example Assistant."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/example"
allowed_hosts = []
genesis = "Handle examples safely."
"""

SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def test_validates_manifest_through_genesis() -> None:
    _native.validate_manifest(MANIFEST)

    with pytest.raises(ValueError, match="unsupported Assistant spec"):
        _native.validate_manifest(MANIFEST.replace("spec = 1", "spec = 4"))


def test_builds_contract_through_genesis() -> None:
    powers = [
        {
            "id": "example",
            "accounts": [],
            "input_schema": SCHEMA,
            "output_schema": SCHEMA,
        }
    ]

    contract = json.loads(_native.build_contract(MANIFEST, json.dumps(powers)))

    assert contract["version"] == 1
    assert contract["powers"][0]["id"] == "example"


def test_validates_private_values_without_leaking_them() -> None:
    schema = {"type": "string", "pattern": "^public$"}

    with pytest.raises(ValueError, match="value does not match schema") as captured:
        _native.validate_json(json.dumps(schema), json.dumps("private-token"))

    assert "private-token" not in str(captured.value)
