"""The stable logical operation id, from the private invocation to Context."""

import io
import json
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz import Context
from shimpz._bridge import _request, dispatch

ROOT = Path(__file__).parents[2]
VECTORS = ROOT / "crates/shimpz-genesis/protocol/assistant/v1/invocation-vectors.json"
OPERATION_ID = "6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"
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

from shimpz import Context, action


class Result(TypedDict):
    operation_id: str


@action()
async def run(*, ctx: Context) -> Result:
    return {"operation_id": ctx.operation_id}
"""


def test_context_exposes_the_assigned_operation_id() -> None:
    assert Context({}, operation_id=OPERATION_ID).operation_id == OPERATION_ID


def test_context_outside_an_invocation_has_no_operation_id() -> None:
    with pytest.raises(RuntimeError, match="only during a Team invocation"):
        _ = Context({}).operation_id


@pytest.mark.parametrize("value", [OPERATION_ID.upper(), OPERATION_ID.replace("-4", "-1", 1), "", 7])
def test_context_refuses_a_non_canonical_operation_id(value: object) -> None:
    with pytest.raises(ValueError, match="operation_id is invalid"):
        Context({}, operation_id=value)  # type: ignore[arg-type]


def test_the_action_receives_the_invocation_operation_id(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    (root / "actions").mkdir(parents=True)
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    (root / "actions" / "echo.py").write_text(ACTION, encoding="utf-8")
    request = {"input": {}, "integrations": {}, "stored_inputs": {}, "files": {}, "operation_id": OPERATION_ID}

    response = json.loads(dispatch(["invoke", str(root), "echo"], io.StringIO(json.dumps(request))))

    assert response == {"type": "result", "result": {"operation_id": OPERATION_ID}}


def test_private_requests_match_every_invocation_vector() -> None:
    for case in json.loads(VECTORS.read_bytes())["cases"]:
        try:
            _request(io.StringIO(json.dumps(case["invocation"])))
        except ValueError:
            admitted = False
        else:
            admitted = True
        assert admitted == case["valid"], case["name"]
