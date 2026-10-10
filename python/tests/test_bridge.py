"""Tests for the private Rust CLI bridge."""

import base64
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz._bridge import dispatch

OPERATION_ID = "6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"

MANIFEST = """
[shimpz]
spec = 1
id = "example"
version = "0.1.0"
name = "Example"
summary = "Test an example."
description = "Runs only the reviewed Actions of this Assistant."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/example"
genesis = "Test examples safely."

[network]
allowed_hosts = ["graph.facebook.com"]
"""

ACTION = """
from typing import TypedDict

from shimpz import action


class Result(TypedDict):
    greeting: str


@action(description="Runs one reviewed operation.")
async def run(name: str) -> Result:
    return {"greeting": f"Hello, {name}"}
"""

HUMAN_ACTION = """
from typing import TypedDict

from shimpz import Context, action, identifier, text


class Result(TypedDict):
    approved: bool


@action(description="Runs one reviewed operation.", human_requests=["approval"])
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


@action(description="Runs one reviewed operation.", stored_inputs=["whatsapp-token"], human_requests=["input:password"])
async def run(name: str, *, ctx: Context) -> Result:
    ctx.request_input(InputRequest(
        "password",
        text("WhatsApp token"),
        text("Enter the token used by this WhatsApp Action."),
        text("Token"),
        min_length=1,
        stored_input="whatsapp-token",
    ))
    response = await ctx.fetch("GET", "https://graph.facebook.com/v26.0/me", headers={"Accept": "application/json"})
    if response.status == 401:
        ctx.reject_stored_input("whatsapp-token")
    return {"accepted": response.json()["name"] == name}
"""


PAIR_ACTION = """
from typing import TypedDict

from shimpz import Context, InputRequest, action, text


class Result(TypedDict):
    accepted: bool


def slot(stored_input: str) -> InputRequest:
    return InputRequest(
        "password",
        text("WhatsApp token"),
        text("Enter the token used by this WhatsApp Action."),
        text("Token"),
        min_length=1,
        stored_input=stored_input,
    )


@action(description="Runs one reviewed operation.", stored_inputs=["whatsapp-app-secret", "whatsapp-token"], human_requests=["input:password"])
async def run(name: str, *, ctx: Context) -> Result:
    ctx.request_stored_inputs(slot("whatsapp-token"), slot("whatsapp-app-secret"))
    if name == "invalid":
        ctx.reject_stored_input("whatsapp-app-secret")
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
    assert contract["actions"][0]["description"] == "Runs one reviewed operation."
    assert {message["msgid"]: message["max_length"] for message in contract["messages"]} == {
        "Test an example.": 80,
        "Runs only the reviewed Actions of this Assistant.": 500,
        "Runs one reviewed operation.": 120,
    }


def test_invokes_a_action_from_a_stdin_request(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO(
        json.dumps(
            {
                "input": {"name": "Ada"},
                "stored_inputs": [],
                "files": {},
                "operation_id": OPERATION_ID,
            }
        )
    )

    result = json.loads(dispatch(["invoke", str(root), "greet"], request))

    assert result == {"type": "result", "result": {"greeting": "Hello, Ada"}}


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO(
        '{"input":{"name":"Ada","name":"Lin"},"stored_inputs":[],"files":{},"operation_id":"6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"}'
    )

    with pytest.raises(ValueError, match="request is invalid"):
        dispatch(["invoke", str(root), "greet"], request)


def test_returns_a_tagged_request_and_replays_its_response(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", HUMAN_ACTION)
    invocation = {
        "input": {"name": "Ada"},
        "stored_inputs": [],
        "files": {},
        "operation_id": OPERATION_ID,
    }

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


STORED_MANIFEST = (
    MANIFEST
    + """
[stored_inputs.whatsapp-token]
kind = "password"
label = "WhatsApp token"
description = "Token used to call the WhatsApp API."
help_url = "https://dashboard.example.com/api-keys"
host = "graph.facebook.com"
routes = [{ method = "POST", path = "/v23.0/*/messages" }]
header = "Authorization"
scheme = "Bearer"
"""
)
STORED_INVOCATION = {"input": {"name": "Ada"}, "stored_inputs": ["whatsapp-token"], "files": {}, "operation_id": OPERATION_ID}


def _exchange(root: Path, *replies: object) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Run one invocation line followed by Team's reply lines; return the terminal and the calls the Action wrote."""
    lines = [json.dumps(STORED_INVOCATION), *(json.dumps(reply) for reply in replies)]
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        terminal = json.loads(dispatch(["invoke", str(root), "greet"], io.StringIO("\n".join(lines) + "\n")))
    return terminal, [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_a_provider_call_crosses_the_channel_without_any_credential(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", STORED_ACTION, STORED_MANIFEST)
    body = base64.b64encode(b'{"name":"Ada"}').decode()

    terminal, calls = _exchange(root, {"status": 200, "headers": [["Content-Type", "application/json"]], "body": body})

    assert terminal == {"type": "result", "result": {"accepted": True}}
    assert calls == [
        {
            "type": "fetch",
            "method": "GET",
            "url": "https://graph.facebook.com/v26.0/me",
            "headers": [["Accept", "application/json"]],
        }
    ]


def test_a_provider_rejection_lets_the_action_reject_its_stored_input(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", STORED_ACTION, STORED_MANIFEST)

    terminal, _ = _exchange(root, {"status": 401, "headers": [], "body": ""})

    assert terminal == {"type": "stored_input_rejected", "stored_input": "whatsapp-token"}


@pytest.mark.parametrize("code", ["refused", "credential-missing", "unavailable", "failed"])
def test_a_team_refusal_raises_fetch_error_in_the_action(tmp_path: Path, code: str) -> None:
    root = create_project(tmp_path / "assistant", STORED_ACTION, STORED_MANIFEST)

    terminal, _ = _exchange(root, {"error": code})

    assert terminal["type"] == "failure"
    assert terminal["failure"]["error_type"] == "shimpz.fetch.FetchError"


@pytest.mark.parametrize(
    "reply",
    [{"status": 200, "headers": [], "body": "not base64!"}, {"status": 99, "headers": [], "body": ""}, {"error": "x"}],
)
def test_a_malformed_reply_fails_the_action(tmp_path: Path, reply: object) -> None:
    root = create_project(tmp_path / "assistant", STORED_ACTION, STORED_MANIFEST)

    terminal, _ = _exchange(root, reply)

    assert terminal["type"] == "failure"


def test_no_human_request_follows_a_provider_call(tmp_path: Path) -> None:
    source = STORED_ACTION.replace(
        "    if response.status == 401:",
        '    ctx.request_input(InputRequest("password", text("WhatsApp token"), '
        'text("Enter the token used by this WhatsApp Action."), text("Token"), stored_input="whatsapp-token"))\n'
        "    if response.status == 401:",
    )
    root = create_project(tmp_path / "assistant", source, STORED_MANIFEST)

    terminal, _ = _exchange(root, {"status": 200, "headers": [], "body": ""})

    assert terminal["type"] == "failure"
    assert "after a provider call" in terminal["failure"]["message"]


def test_two_stored_inputs_suspend_one_at_a_time_and_reject_only_the_refused_one(tmp_path: Path) -> None:
    manifest = (
        MANIFEST
        + """
[stored_inputs.whatsapp-token]
kind = "password"
label = "WhatsApp token"
description = "Token used to call the WhatsApp API."
help_url = "https://dashboard.example.com/api-keys"
host = "graph.facebook.com"
routes = [{ method = "POST", path = "/v23.0/*/messages" }]
header = "Authorization"
scheme = "Bearer"

[stored_inputs.whatsapp-app-secret]
kind = "password"
label = "WhatsApp app secret"
description = "App secret used to sign WhatsApp API calls."
help_url = "https://dashboard.example.com/api-keys"
host = "graph.facebook.com"
routes = [{ method = "POST", path = "/v23.0/*/messages" }]
query = "appsecret_proof"
hmac = "whatsapp-token"
"""
    )
    root = create_project(tmp_path / "assistant", PAIR_ACTION, manifest)

    def invoke(stored_inputs: list[str], name: str = "Ada") -> dict[str, object]:
        invocation = {
            "input": {"name": name},
            "stored_inputs": stored_inputs,
            "files": {},
            "operation_id": OPERATION_ID,
        }
        return json.loads(dispatch(["invoke", str(root), "greet"], io.StringIO(json.dumps(invocation))))

    first = invoke([])
    assert (first["type"], first["request"]["stored_input"], first["request"]["ordinal"]) == (
        "request",
        "whatsapp-token",
        0,
    )
    second = invoke(["whatsapp-token"])
    assert (second["request"]["stored_input"], second["request"]["ordinal"]) == ("whatsapp-app-secret", 0)
    assert invoke(["whatsapp-app-secret", "whatsapp-token"]) == {
        "type": "result",
        "result": {"accepted": True},
    }
    assert invoke(["whatsapp-app-secret", "whatsapp-token"], "invalid") == {
        "type": "stored_input_rejected",
        "stored_input": "whatsapp-app-secret",
    }


def test_requires_the_current_stored_input_invocation_field(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    request = io.StringIO(
        '{"input":{"name":"Ada"},"stored_inputs":{"whatsapp-token":"value"},"files":{},'
        '"operation_id":"6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"}'
    )

    with pytest.raises(ValueError, match="request is invalid"):
        dispatch(["invoke", str(root), "greet"], request)


def test_returns_the_catalog_without_importing_creator_code_or_its_dependencies(tmp_path: Path) -> None:
    marker = tmp_path / "imported"
    source = HUMAN_ACTION.replace(
        "from shimpz import Context, action, identifier, text",
        f"import not_an_installed_dependency\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
        "from shimpz import Context, action, identifier, text",
    )
    root = create_project(tmp_path / "assistant", source)

    document = json.loads(dispatch(["catalog", str(root)], io.StringIO("")))

    assert set(document) == {"summary", "messages"}
    assert document["summary"] == "Test an example."
    assert sorted(message["msgid"] for message in document["messages"]) == [
        "Runs one reviewed operation.",
        "Runs only the reviewed Actions of this Assistant.",
        "Send a greeting to {name}.",
        "Send greeting",
        "Test an example.",
    ]
    assert [message["id"] for message in document["messages"]] == sorted(
        message["id"] for message in document["messages"]
    )
    assert not marker.exists()
