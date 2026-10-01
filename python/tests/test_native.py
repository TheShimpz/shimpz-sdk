"""Native Genesis boundary tests."""

import hashlib
import json

import pytest
from shimpz import _native

MANIFEST = """
[shimpz]
spec = 1
id = "example"
version = "0.1.0"
name = "Example"
summary = "Example Assistant."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/example"
genesis = "Handle examples safely."

[network]
allowed_hosts = []
"""

SUMMARY = json.dumps(
    [
        {
            "id": hashlib.sha256(b"Example Assistant.").hexdigest(),
            "msgid": "Example Assistant.",
            "max_length": 160,
            "params": [],
        }
    ]
)

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
    actions = [
        {
            "id": "example",
            "integrations": [],
            "stored_inputs": [],
            "human_requests": [],
            "input_schema": SCHEMA,
            "output_schema": SCHEMA,
        }
    ]

    contract = json.loads(_native.build_contract(MANIFEST, json.dumps(actions), SUMMARY))

    assert contract["version"] == 1
    assert contract["actions"][0]["id"] == "example"
    assert contract["messages"] == json.loads(SUMMARY)


def test_refuses_a_catalog_without_the_summary_message() -> None:
    actions = [
        {
            "id": "example",
            "integrations": [],
            "stored_inputs": [],
            "human_requests": [],
            "input_schema": SCHEMA,
            "output_schema": SCHEMA,
        }
    ]
    other = [{"id": hashlib.sha256(b"Other.").hexdigest(), "msgid": "Other.", "max_length": 160, "params": []}]

    with pytest.raises(ValueError, match="summary"):
        _native.build_contract(MANIFEST, json.dumps(actions), json.dumps(other))


def test_refuses_a_dense_action_schema_before_publication() -> None:
    dense = {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {"p": {"type": "string", "enum": [f"v{index}" for index in range(4_089)]}},
    }
    actions = [
        {
            "id": "example",
            "integrations": [],
            "stored_inputs": [],
            "human_requests": [],
            "input_schema": dense,
            "output_schema": SCHEMA,
        }
    ]

    with pytest.raises(ValueError, match="Action schema has too many JSON values"):
        _native.build_contract(MANIFEST, json.dumps(actions), SUMMARY)


def test_validates_private_values_without_leaking_them() -> None:
    schema = {"type": "string", "pattern": "^public$"}

    with pytest.raises(ValueError, match="value does not match schema") as captured:
        _native.validate_json(json.dumps(schema), json.dumps("private-token"))

    assert "private-token" not in str(captured.value)
