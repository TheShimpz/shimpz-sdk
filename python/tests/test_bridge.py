"""Tests for the private Rust CLI bridge."""

import hashlib
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

ACTION = """
from typing import TypedDict

from shimpz import action


class Result(TypedDict):
    greeting: str


@action()
async def run(name: str) -> Result:
    return {"greeting": f"Hello, {name}"}
"""

HUMAN_ACTION = """
from typing import TypedDict

from shimpz import Context, action, identifier, text


class Result(TypedDict):
    approved: bool


@action(human_requests=["approval"])
async def run(name: str, *, ctx: Context) -> Result:
    ctx.request_approval(
        title=text("Send greeting"),
        description=text("Send a greeting to {name}.", name=identifier(name, max_length=32)),
    )
    return {"approved": True}
"""

STORED_ACTION = """
from typing import TypedDict

from shimpz import Context, InputRequest, action, text


class Result(TypedDict):
    accepted: bool


@action(stored_inputs=["whatsapp-token"], human_requests=["input:password"])
async def run(name: str, *, ctx: Context) -> Result:
    token = ctx.request_input(InputRequest(
        "password",
        text("WhatsApp token"),
        text("Enter the token used by this WhatsApp Action."),
        text("Token"),
        min_length=1,
        stored_input="whatsapp-token",
    ))
    if token == "invalid":
        ctx.reject_stored_input("whatsapp-token")
    return {"accepted": True}
"""


def create_project(root: Path, source: str = ACTION, manifest: str = MANIFEST) -> Path:
    root.mkdir()
    write_icon(root)
    (root / "shimpz.toml").write_text(manifest, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    actions = root / "actions"
    actions.mkdir()
    (actions / "greet.py").write_text(source, encoding="utf-8")
    return root


def test_builds_a_contract_for_the_rust_cli(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")

    contract = json.loads(dispatch(["contract", str(root)], io.StringIO("")))

    assert contract["actions"][0]["id"] == "greet"
    assert [message["msgid"] for message in contract["messages"]] == ["Test an example."]


def test_invokes_a_action_from_a_stdin_request(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO('{"input":{"name":"Ada"},"integrations":{},"stored_inputs":{}}')

    result = json.loads(dispatch(["invoke", str(root), "greet"], request))

    assert result == {"type": "result", "result": {"greeting": "Hello, Ada"}}


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO(
        '{"input":{"name":"Ada","name":"Lin"},"integrations":{},"stored_inputs":{}}'
    )

    with pytest.raises(ValueError, match="request is invalid"):
        dispatch(["invoke", str(root), "greet"], request)


def test_returns_a_tagged_request_and_replays_its_response(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", HUMAN_ACTION)
    invocation = {"input": {"name": "Ada"}, "integrations": {}, "stored_inputs": {}}

    suspended = json.loads(dispatch(["invoke", str(root), "greet"], io.StringIO(json.dumps(invocation))))

    assert suspended["type"] == "request"
    frame = suspended["request"]
    assert frame["description"] == {
        "message": hashlib.sha256(b"Send a greeting to {name}.").hexdigest(),
        "params": {"name": "Ada"},
    }
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

    rendered = json.loads(dispatch(["render", str(root)], io.StringIO(json.dumps({"request": frame}))))
    assert rendered == {
        **frame,
        "title": "Send greeting",
        "description": "Send a greeting to Ada.",
    }
    forged = {**frame, "description": {**frame["description"], "params": {"name": "Lin"}}}
    with pytest.raises(ValueError, match="request is invalid"):
        dispatch(["render", str(root)], io.StringIO(json.dumps({"request": forged})))


def test_reuses_and_explicitly_rejects_one_stored_input(tmp_path: Path) -> None:
    manifest = (
        MANIFEST
        + """
[stored_inputs.whatsapp-token]
kind = "password"
label = "WhatsApp token"
description = "Token used to call the WhatsApp API."
"""
    )
    root = create_project(tmp_path / "assistant", STORED_ACTION, manifest)
    invocation = {
        "input": {"name": "Ada"},
        "integrations": {},
        "stored_inputs": {"whatsapp-token": "invalid"},
    }

    rejected = json.loads(dispatch(["invoke", str(root), "greet"], io.StringIO(json.dumps(invocation))))

    assert rejected == {
        "type": "stored_input_rejected",
        "stored_input": "whatsapp-token",
    }


def test_requires_the_current_stored_input_invocation_field(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO('{"input":{"name":"Ada"},"integrations":{}}')

    with pytest.raises(ValueError, match="request is invalid"):
        dispatch(["invoke", str(root), "greet"], request)
