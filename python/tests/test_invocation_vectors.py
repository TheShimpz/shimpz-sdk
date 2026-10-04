"""The Assistant Spec v1 invocation vectors round-trip through the private bridge (ADR-0093).

Team and Developers freeze the same ``vectors/invocation.json`` and ``vectors/file-invocation.json`` that this mirror
pins, so every invocation Team emits is parsed here exactly as the bridge parses a stdin frame.
"""

import io
import json
from pathlib import Path

import pytest
from shimpz._bridge import _request, dispatch
from shimpz._files import bind_files
from test_bridge import OPERATION_ID, create_project

VECTORS = Path(__file__).parents[2] / "crates/shimpz-genesis/protocol/assistant/v1/vectors"
INVOCATIONS = json.loads((VECTORS / "invocation.json").read_bytes())["cases"]
FILE_INVOCATIONS = json.loads((VECTORS / "file-invocation.json").read_bytes())["cases"]


def _admitted(frame: object) -> dict[str, object] | None:
    try:
        return _request(io.StringIO(json.dumps(frame)))
    except ValueError:
        return None


@pytest.mark.parametrize("case", INVOCATIONS, ids=lambda case: case["name"])
def test_the_bridge_admits_exactly_the_valid_invocation_vectors(case: dict[str, object]) -> None:
    assert (_admitted(case["invocation"]) is not None) == case["valid"]


@pytest.mark.parametrize("case", FILE_INVOCATIONS, ids=lambda case: case["name"])
def test_the_bridge_and_binding_admit_exactly_the_valid_file_invocation_vectors(case: dict[str, object]) -> None:
    action = case["action"]
    payload = _admitted(case["invocation"])
    admitted = False
    if payload is not None:
        try:
            bound = bind_files(action, payload["input"], payload["files"], payload.get("responses", []))
        except ValueError:
            pass
        else:
            admitted = True
            assert set(bound) == set(action["input_files"])
            assert [file.id for file in bound.values()] == list(payload["files"])
    assert admitted == case["valid"]


def test_an_ordinary_invocation_with_empty_files_runs_the_action(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    frame = {"input": {"name": "Ada"}, "integrations": {}, "stored_inputs": {}, "files": {}, "operation_id": OPERATION_ID}

    result = json.loads(dispatch(["invoke", str(root), "greet"], io.StringIO(json.dumps(frame))))

    assert result == {"type": "result", "result": {"greeting": "Hello, Ada"}}


@pytest.mark.parametrize("files", [None, [], "", {"": {}}, {"0123456789abcdef0123456789abcdef": None}])
def test_an_invocation_without_a_well_formed_files_object_is_refused(tmp_path: Path, files: object) -> None:
    root = create_project(tmp_path / "assistant")
    frame: dict[str, object] = {"input": {"name": "Ada"}, "integrations": {}, "stored_inputs": {}}
    frame["operation_id"] = OPERATION_ID
    if files is not None:
        frame["files"] = files

    with pytest.raises(ValueError, match="private bridge request is invalid"):
        dispatch(["invoke", str(root), "greet"], io.StringIO(json.dumps(frame)))


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("integrations", {"cloudflare": "t" * 16385}),
        ("integrations", {"cloudflare": ""}),
        ("integrations", {f"provider-{index}": "token" for index in range(5)}),
        ("integrations", {"Cloudflare": "token"}),
        ("integrations", {"a" * 65: "token"}),
        ("stored_inputs", {"whatsapp-token": "t" * 1025}),
        ("stored_inputs", {"whatsapp_token": "token"}),
        ("stored_inputs", {"first": "token", "second": "token"}),
    ],
)
def test_an_integration_or_stored_input_outside_the_schema_is_refused(member: str, value: object) -> None:
    frame = {"input": {}, "integrations": {}, "stored_inputs": {}, "files": {}, "operation_id": OPERATION_ID}
    frame[member] = value

    assert _admitted(frame) is None


def test_integration_and_stored_input_bounds_are_inclusive() -> None:
    frame = {
        "input": {},
        "integrations": {f"provider-{index}": "t" * 16384 for index in range(4)},
        "stored_inputs": {"whatsapp-token": "t" * 1024},
        "files": {},
        "operation_id": OPERATION_ID,
    }

    assert _admitted(frame) is not None
