"""Native Genesis boundary tests."""

import hashlib
import json
import re
from typing import Annotated

import pytest
from shimpz import _native
from shimpz._schema import schema_for_type

MANIFEST = """
[shimpz]
spec = 1
id = "example"
version = "0.1.0"
name = "Example"
summary = "Example Assistant."
description = "Runs only the reviewed Actions of this Assistant."
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
            "max_length": 80,
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


def test_validates_the_assistant_page_copy_through_genesis() -> None:
    description = 'description = "Runs only the reviewed Actions of this Assistant."'
    _native.validate_manifest(MANIFEST.replace(description, f'description = "{"\U0001f600" * 400}"'))
    links = '[shimpz.links]\nsite = "https://example.org/"\nyoutube = "https://www.youtube.com/@example"\n\n[network]'
    _native.validate_manifest(MANIFEST.replace("[network]", links))

    with pytest.raises(ValueError, match=r"shimpz\.toml is invalid"):
        _native.validate_manifest(MANIFEST.replace(description + "\n", ""))
    with pytest.raises(ValueError, match="description is invalid"):
        _native.validate_manifest(MANIFEST.replace(description, f'description = "{"a" * 401}"'))
    with pytest.raises(ValueError, match=r"links\.youtube is invalid"):
        _native.validate_manifest(
            MANIFEST.replace("[network]", links.replace("www.youtube.com", "youtube.com.evil.org"))
        )


def test_builds_contract_through_genesis() -> None:
    actions = [
        {
            "id": "example",
            "description": "Runs one example.",
            "integrations": [],
            "stored_inputs": [],
            "input_files": [],
            "human_requests": [],
            "effect": "read_only",
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
            "description": "Runs one example.",
            "integrations": [],
            "stored_inputs": [],
            "input_files": [],
            "human_requests": [],
            "effect": "read_only",
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
            "description": "Runs one example.",
            "integrations": [],
            "stored_inputs": [],
            "input_files": [],
            "human_requests": [],
            "effect": "read_only",
            "input_schema": dense,
            "output_schema": SCHEMA,
        }
    ]

    with pytest.raises(ValueError, match="Action schema has too many JSON values"):
        _native.build_contract(MANIFEST, json.dumps(actions), SUMMARY)


def _pattern_actions(pattern: str) -> str:
    field = schema_for_type(Annotated[str, {"pattern": pattern}])
    schema = {**SCHEMA, "properties": {"value": field}}
    return json.dumps(
        [
            {
                "id": "example",
                "description": "Runs one example.",
                "integrations": [],
                "stored_inputs": [],
                "input_files": [],
                "human_requests": [],
                "effect": "read_only",
                "input_schema": schema,
                "output_schema": SCHEMA,
            }
        ]
    )


@pytest.mark.parametrize("pattern", [r"^[a-z0-9_-]{1,64}$", r"(?i)^\w+$", r"^(?P<zone>[a-z]+)\.example$"])
def test_admits_an_annotated_pattern_publication_admits(pattern: str) -> None:
    _native.build_contract(MANIFEST, _pattern_actions(pattern), SUMMARY)


@pytest.mark.parametrize(
    "pattern", [r"(?x)^[a-z]+$", r"\u0041", r"a{1001}", r"a{1, 2}", r"(?:a{100}){11}", "^.{1,1000}$"]
)
def test_refuses_an_annotated_pattern_publication_refuses(pattern: str) -> None:
    re.compile(pattern)

    with pytest.raises(ValueError, match="Action schema pattern is invalid"):
        _native.build_contract(MANIFEST, _pattern_actions(pattern), SUMMARY)


@pytest.mark.parametrize(("pattern", "subject"), [(r"^\d$", "\u0663"), (r"^\s$", "\v"), (r"\bé", "é")])
def test_matches_patterns_with_team_re2_semantics(pattern: str, subject: str) -> None:
    with pytest.raises(ValueError, match="value does not match schema"):
        _native.validate_json(json.dumps({"type": "string", "pattern": pattern}), json.dumps(subject))


def test_validates_private_values_without_leaking_them() -> None:
    schema = {"type": "string", "pattern": "^public$"}

    with pytest.raises(ValueError, match="value does not match schema") as captured:
        _native.validate_json(json.dumps(schema), json.dumps("private-token"))

    assert "private-token" not in str(captured.value)
