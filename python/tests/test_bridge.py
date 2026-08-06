"""Tests for the private Rust CLI bridge."""

import io
import json
from pathlib import Path

import pytest
from _fixtures import write_icon
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

HUMAN_POWER = """
from typing import TypedDict

from shimpz import Context, power


class Result(TypedDict):
    approved: bool


@power(human_requests=["approval"])
async def run(name: str, *, ctx: Context) -> Result:
    ctx.request_approval(
        title="Send greeting",
        description=f"Send a greeting to {name}.",
    )
    return {"approved": True}
"""


def create_project(root: Path, source: str = POWER) -> Path:
    root.mkdir()
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    powers = root / "powers"
    powers.mkdir()
    (powers / "greet.py").write_text(source, encoding="utf-8")
    return root


def test_builds_a_contract_for_the_rust_cli(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")

    contract = json.loads(dispatch(["contract", str(root)], io.StringIO("")))

    assert contract["powers"][0]["id"] == "greet"


def test_invokes_a_power_from_a_stdin_request(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO('{"input":{"name":"Ada"},"integrations":{}}')

    result = json.loads(dispatch(["invoke", str(root), "greet"], request))

    assert result == {"type": "result", "result": {"greeting": "Hello, Ada"}}


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO('{"input":{"name":"Ada","name":"Lin"},"integrations":{}}')

    with pytest.raises(ValueError, match="request is invalid"):
        dispatch(["invoke", str(root), "greet"], request)


def test_returns_a_tagged_request_and_replays_its_response(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", HUMAN_POWER)
    invocation = {"input": {"name": "Ada"}, "integrations": {}}

    suspended = json.loads(dispatch(["invoke", str(root), "greet"], io.StringIO(json.dumps(invocation))))

    assert suspended["type"] == "request"
    frame = suspended["request"]
    invocation["responses"] = [
        {
            "kind": frame["kind"],
            "ordinal": frame["ordinal"],
            "fingerprint": frame["fingerprint"],
            "value": True,
        }
    ]

    completed = json.loads(dispatch(["invoke", str(root), "greet"], io.StringIO(json.dumps(invocation))))
    assert completed == {"type": "result", "result": {"approved": True}}
