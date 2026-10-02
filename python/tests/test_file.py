"""Action file inputs: generation, metadata-first delivery, and invocation bounds (ADR-0093)."""

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz import File, FileContentWithheldError
from shimpz._bridge import dispatch
from shimpz._files import bind_files
from shimpz._project import AssistantProject

ROOT = Path(__file__).parents[2]
VECTORS = ROOT / "crates/shimpz-genesis/protocol/assistant/v1/file-invocation-vectors.json"
OPERATION_ID = "6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"
FILE_ID = "0123456789abcdef0123456789abcdef"
CONTENT = b"name,amount\nexample,42\n"
FILE_ID_SCHEMA = {"type": "string", "minLength": 32, "maxLength": 32, "pattern": "^[0-9a-f]{32}$"}

MANIFEST = """
[shimpz]
spec = 1
id = "documents"
version = "0.1.0"
name = "Documents"
summary = "Store reviewed documents."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/documents"
genesis = "Store documents only after approval."

[network]
allowed_hosts = []
"""

ACTION = """
from typing import TypedDict

from shimpz import Context, File, action, text


class Result(TypedDict):
    name: str
    digest: str
    bytes: int


@action(human_requests=["approval"])
async def run(document: File, folder: str, *, ctx: Context) -> Result:
    ctx.request_approval(title=text("Store the document"), description=text("Store the selected document."))
    return {"name": document.name, "digest": document.sha256, "bytes": len(document.read())}
"""

EARLY_READ = """
from typing import TypedDict

from shimpz import Context, File, action, text


class Result(TypedDict):
    bytes: int


@action(human_requests=["approval"])
async def run(document: File, *, ctx: Context) -> Result:
    size = len(document.read())
    ctx.request_approval(title=text("Store the document"), description=text("Store the selected document."))
    return {"bytes": size}
"""

UNAUTHORIZED = """
from typing import TypedDict

from shimpz import File, action


class Result(TypedDict):
    name: str


@action()
async def run(document: File) -> Result:
    return {"name": document.name}
"""

NESTED = """
from typing import TypedDict

from shimpz import File, action


class Upload(TypedDict):
    document: File


class Result(TypedDict):
    name: str


@action(human_requests=["approval"])
async def run(upload: Upload) -> Result:
    return {"name": "never"}
"""


def create_project(root: Path, source: str = ACTION) -> Path:
    root.mkdir()
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    (root / "actions").mkdir()
    (root / "actions" / "store.py").write_text(source, encoding="utf-8")
    return root


def record(content: dict[str, object], data: bytes = CONTENT) -> dict[str, object]:
    return {
        "name": "invoices.csv",
        "media_type": "text/csv",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content": content,
    }


def invocation(content: dict[str, object], responses: list[dict[str, object]] | None = None, **extra: object) -> str:
    value = {
        "input": {"document": FILE_ID, **extra},
        "integrations": {},
        "stored_inputs": {},
        "files": {FILE_ID: record(content)},
        "operation_id": OPERATION_ID,
    }
    if responses is not None:
        value["responses"] = responses
    return json.dumps(value)


def invoke(root: Path, request: str) -> dict[str, object]:
    return json.loads(dispatch(["invoke", str(root), "store"], io.StringIO(request)))


def approve(root: Path) -> list[dict[str, object]]:
    suspended = invoke(root, invocation({"type": "withheld"}, folder="invoices"))
    assert suspended["type"] == "request"
    frame = suspended["request"]
    return [{"ordinal": 0, "fingerprint": frame["fingerprint"], "kind": "approval", "value": True}]


def test_a_file_parameter_generates_the_declaration_and_exact_schema(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")

    action = json.loads(AssistantProject.load(root).contract())["actions"][0]

    assert action["input_files"] == ["document"]
    assert action["input_schema"]["properties"]["document"] == FILE_ID_SCHEMA
    assert action["input_schema"]["properties"]["folder"] == {"type": "string"}
    assert action["input_schema"]["required"] == ["document", "folder"]


def test_a_file_input_without_authorization_cannot_be_published(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", UNAUTHORIZED)

    with pytest.raises(ValueError, match="authorization"):
        AssistantProject.load(root).contract()


def test_a_nested_file_annotation_is_refused(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", NESTED)

    with pytest.raises(TypeError, match="unsupported Action type annotation"):
        AssistantProject.load(root)


def test_the_first_invocation_receives_metadata_and_the_approved_replay_receives_bytes(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    responses = approve(root)
    delivered = {"type": "delivered", "base64": base64.b64encode(CONTENT).decode()}

    result = invoke(root, invocation(delivered, responses, folder="invoices"))

    assert result == {
        "type": "result",
        "result": {"name": "invoices.csv", "digest": hashlib.sha256(CONTENT).hexdigest(), "bytes": len(CONTENT)},
    }


def test_reading_withheld_content_fails_instead_of_returning_an_empty_file(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", EARLY_READ)

    failure = invoke(root, invocation({"type": "withheld"}))

    assert failure["type"] == "failure"
    assert failure["failure"]["error_type"] == "shimpz.file.FileContentWithheldError"


@pytest.mark.parametrize(
    ("content", "approved"),
    [
        ({"type": "delivered", "base64": base64.b64encode(CONTENT).decode()}, False),
        ({"type": "withheld"}, True),
        ({"type": "delivered", "base64": base64.b64encode(b"x" * len(CONTENT)).decode()}, True),
    ],
)
def test_a_file_outside_the_two_phase_rule_never_reaches_action_code(
    tmp_path: Path, content: dict[str, object], *, approved: bool
) -> None:
    root = create_project(tmp_path / "assistant")
    responses = approve(root) if approved else None

    with pytest.raises(ValueError, match="files do not match"):
        invoke(root, invocation(content, responses, folder="invoices"))


def test_an_ordinary_invocation_stays_within_512_kib(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    padding = "a" * (512 * 1024)

    with pytest.raises(ValueError, match="request is invalid"):
        invoke(root, invocation({"type": "withheld"}, folder=padding))


def test_delivered_content_admits_an_8_mib_file_within_12_mib(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    responses = approve(root)
    data = bytes(range(256)) * (8 * 1024 * 4)
    value = json.loads(invocation({"type": "withheld"}, responses, folder="invoices"))
    value["files"][FILE_ID] = record({"type": "delivered", "base64": base64.b64encode(data).decode()}, data)

    result = invoke(root, json.dumps(value))

    assert result["type"] == "result"
    assert result["result"]["bytes"] == 8 * 1024 * 1024
    value["input"]["folder"] = "a" * (1024 * 1024 + 512 * 1024)
    with pytest.raises(ValueError, match="request is invalid"):
        invoke(root, json.dumps(value))


def test_file_is_immutable_and_never_shows_its_bytes() -> None:
    document = File(FILE_ID, "a.txt", "text/plain", 1, "0" * 64, b"a")
    withheld = File(FILE_ID, "a.txt", "text/plain", 1, "0" * 64)

    assert not withheld.delivered
    with pytest.raises(FileContentWithheldError, match="withheld"):
        withheld.read()
    assert document.delivered
    assert document.read() == b"a"
    assert "_content" not in repr(document)
    with pytest.raises(AttributeError):
        document.name = "b.txt"  # type: ignore[misc]


@pytest.mark.parametrize("case", json.loads(VECTORS.read_bytes())["cases"], ids=lambda case: case["name"])
def test_binding_matches_every_file_invocation_vector(case: dict[str, object]) -> None:
    action, value = case["action"], case["invocation"]
    try:
        bound = bind_files(action, value["input"], value.get("files", {}), value.get("responses", []))
    except KeyError, TypeError, ValueError:
        admitted = False
    else:
        admitted = True
        assert set(bound) == set(action["input_files"])
    assert admitted == case["valid"]
