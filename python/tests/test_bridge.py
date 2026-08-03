"""Tests for the private Rust CLI bridge."""

import io
import json
from pathlib import Path

import pytest
from shimpz._bridge import dispatch

MANIFEST = """
[shimpz]
spec = 1
id = "example"
version = "0.1.0"
name = "Example"
summary = "Test an example."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/example"
genesis = "Test examples safely."

[network]
allowed_hosts = []
"""

POWER = """
from typing import TypedDict

from shimpz import power


class Result(TypedDict):
    greeting: str


@power()
async def run(name: str) -> Result:
    return {"greeting": f"Hello, {name}"}
"""


def create_project(root: Path) -> Path:
    root.mkdir()
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    powers = root / "powers"
    powers.mkdir()
    (powers / "greet.py").write_text(POWER, encoding="utf-8")
    return root


def test_builds_a_contract_for_the_rust_cli(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")

    contract = json.loads(dispatch(["contract", str(root)], io.StringIO("")))

    assert contract["powers"][0]["id"] == "greet"


def test_invokes_a_power_from_a_stdin_request(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO('{"input":{"name":"Ada"},"integrations":{}}')

    result = json.loads(dispatch(["invoke", str(root), "greet"], request))

    assert result == {"greeting": "Hello, Ada"}


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO('{"input":{"name":"Ada","name":"Lin"},"integrations":{}}')

    with pytest.raises(ValueError, match="request is invalid"):
        dispatch(["invoke", str(root), "greet"], request)
