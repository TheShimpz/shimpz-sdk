"""Effect classes and verifier declarations, from the decorator through Genesis."""

import hashlib
import json
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz import Idempotency, Mutating, Verifier, action, from_input, from_operation_id
from shimpz._native import build_contract
from shimpz._project import AssistantProject
from shimpz.action import get_action_metadata
from shimpz.verifier import Binding

ROOT = Path(__file__).parents[2]
VECTORS = ROOT / "crates/shimpz-genesis/protocol/assistant/v1/action-effect-vectors.json"
MANIFEST = """
[shimpz]
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Manage DNS records."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
genesis = "Manage DNS safely."

[network]
allowed_hosts = ["api.example.com"]

[stored_inputs.api-key]
kind = "password"
label = "API key"
description = "Key used to read DNS records."
"""
SUMMARY = "Manage DNS records."
CREATE = """
from typing import TypedDict

from shimpz import Idempotency, Mutating, Verifier, action, from_input, from_operation_id


class Record(TypedDict):
    id: str


@action(
    effect=Mutating(
        idempotency=Idempotency(
            provider="api.example.com",
            key_location="header",
            key_name="Idempotency-Key",
            scope="account",
            retention_seconds=86_400,
            same_payload_required=True,
        ),
        verifier=Verifier(
            action="find-record",
            inputs={"zone": from_input("/zone"), "operation": from_operation_id()},
            outcome="/outcome",
            result="/record",
        ),
    ),
)
async def run(zone: str, name: str) -> Record:
    return {"id": name}
"""
FIND = """
from typing import NotRequired, TypedDict

from shimpz import VerificationOutcome, action


class Record(TypedDict):
    id: str


class Evidence(TypedDict):
    outcome: VerificationOutcome
    record: NotRequired[Record]


@action(effect="read_only")
async def run(zone: str, operation: str) -> Evidence:
    return {"outcome": "inconclusive"}
"""


def _project(root: Path, find: str = FIND) -> AssistantProject:
    root.mkdir()
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    actions = root / "actions"
    actions.mkdir()
    (actions / "create_record.py").write_text(CREATE, encoding="utf-8")
    (actions / "find_record.py").write_text(find, encoding="utf-8")
    return AssistantProject.load(root)


def test_an_undeclared_effect_is_mutating() -> None:
    @action()
    async def run() -> None:
        pass

    metadata = get_action_metadata(run)

    assert metadata is not None
    assert metadata.effect == "mutating"
    assert metadata.verifier is None


def test_the_contract_carries_the_declared_effect_and_verifier(tmp_path: Path) -> None:
    contract = json.loads(_project(tmp_path / "dns").contract())

    create, find = contract["actions"]
    assert create["effect"] == "mutating"
    assert create["verifier"] == {
        "action": "find-record",
        "input": {"zone": {"from": "input", "pointer": "/zone"}, "operation": {"from": "operation_id"}},
        "outcome": "/outcome",
        "result": "/record",
    }
    assert create["idempotency"] == {
        "provider": "api.example.com",
        "key": {"location": "header", "name": "Idempotency-Key"},
        "scope": "account",
        "retention_seconds": 86_400,
        "same_payload_required": True,
    }
    assert find["effect"] == "read_only"
    assert "verifier" not in find
    assert "idempotency" not in find
    assert find["output_schema"]["properties"]["outcome"] == {
        "type": "string",
        "enum": ["occurred", "not_occurred", "inconclusive"],
    }


def test_genesis_refuses_a_verifier_whose_result_differs(tmp_path: Path) -> None:
    project = _project(tmp_path / "dns", FIND.replace("    id: str", "    id: int"))

    with pytest.raises(ValueError, match="outcome or result position"):
        project.contract()


def test_genesis_refuses_a_mutating_verifier(tmp_path: Path) -> None:
    project = _project(tmp_path / "dns", FIND.replace('effect="read_only"', 'effect="mutating"'))

    with pytest.raises(ValueError, match="non-interactive read-only"):
        project.contract()


@pytest.mark.parametrize("effect", ["write", "", None, ["mutating"]])
def test_rejects_an_unknown_effect(effect: object) -> None:
    with pytest.raises(ValueError, match=r"read_only, mutating, or shimpz\.Mutating"):
        action(effect=effect)  # type: ignore[arg-type]


def test_mutating_declarations_are_sdk_values() -> None:
    with pytest.raises(TypeError, match=r"shimpz\.Verifier"):
        Mutating(verifier={"action": "find"})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"shimpz\.Idempotency"):
        Mutating(idempotency=IDEMPOTENCY)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "binding",
    [
        lambda: from_input(""),
        lambda: from_input("zone"),
        lambda: from_input("/zone/"),
        lambda: from_input("/a~2"),
        lambda: from_input("/" + "z" * 256),
        lambda: Binding("input"),
        lambda: Binding("operation_id", "/zone"),
        lambda: Binding("output", "/zone"),  # type: ignore[arg-type]
    ],
)
def test_rejects_an_invalid_binding(binding: object) -> None:
    with pytest.raises(ValueError, match="binding is invalid"):
        binding()  # type: ignore[operator]


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "Find"},
        {"inputs": {}},
        {"inputs": {f"p{index}": from_operation_id() for index in range(17)}},
        {"inputs": {"n" * 129: from_operation_id()}},
        {"inputs": {"zone": "/zone"}},
        {"outcome": "outcome"},
        {"result": "/record/"},
    ],
)
def test_rejects_an_invalid_verifier(changes: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "action": "find",
        "inputs": {"operation": from_operation_id()},
        "outcome": "/outcome",
        "result": "/record",
    }
    fields.update(changes)

    with pytest.raises(ValueError, match="Verifier declaration is invalid"):
        Verifier(**fields)  # type: ignore[arg-type]


def test_verifier_inputs_are_a_read_only_copy() -> None:
    inputs = {"operation": from_operation_id()}
    verifier = Verifier(action="find", inputs=inputs, outcome="/outcome", result="/record")
    inputs["zone"] = from_input("/zone")

    assert list(verifier.inputs) == ["operation"]
    with pytest.raises(TypeError):
        verifier.inputs["zone"] = from_input("/zone")  # type: ignore[index]
    with pytest.raises(TypeError, match="map verifier input names"):
        Verifier(action="find", inputs=[("operation", from_operation_id())], outcome="/o", result="/r")  # type: ignore[arg-type]


def test_native_contract_generation_matches_every_action_effect_vector() -> None:
    summary = json.dumps(
        [{"id": hashlib.sha256(SUMMARY.encode()).hexdigest(), "msgid": SUMMARY, "max_length": 160, "params": []}]
    )
    for case in json.loads(VECTORS.read_bytes())["cases"]:
        try:
            build_contract(MANIFEST, json.dumps(case["actions"]), summary)
        except ValueError:
            admitted = False
        else:
            admitted = True
        assert admitted == case["valid"], case["name"]


def test_genesis_refuses_a_verifier_that_cannot_identify_the_operation(tmp_path: Path) -> None:
    find = FIND.replace("zone: str, operation: str", "zone: str")
    uncorrelated = CREATE.replace(
        'inputs={"zone": from_input("/zone"), "operation": from_operation_id()}', 'inputs={"zone": from_input("/zone")}'
    )
    root = tmp_path / "dns"
    _project(root, find)
    (root / "actions" / "create_record.py").write_text(uncorrelated, encoding="utf-8")

    with pytest.raises(ValueError, match="do not identify the operation"):
        AssistantProject.load(root).contract()


def test_genesis_refuses_an_idempotency_provider_outside_the_allowed_hosts(tmp_path: Path) -> None:
    root = tmp_path / "dns"
    _project(root)
    source = (root / "actions" / "create_record.py").read_text(encoding="utf-8")
    (root / "actions" / "create_record.py").write_text(source.replace("api.example.com", "api.other.example"), "utf-8")

    with pytest.raises(ValueError, match="not an allowed host"):
        AssistantProject.load(root).contract()


IDEMPOTENCY = {
    "provider": "api.example.com",
    "key_location": "header",
    "key_name": "Idempotency-Key",
    "scope": "account",
    "retention_seconds": 86_400,
    "same_payload_required": True,
}


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "localhost"},
        {"provider": "API.example.com"},
        {"key_location": "cookie"},
        {"key_name": "Idempotency Key"},
        {"scope": "global"},
        {"retention_seconds": 59},
        {"retention_seconds": 31_536_001},
        {"retention_seconds": True},
        {"same_payload_required": "yes"},
    ],
)
def test_rejects_an_invalid_idempotency_declaration(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Idempotency declaration is invalid"):
        Idempotency(**{**IDEMPOTENCY, **changes})  # type: ignore[arg-type]


def test_a_mutating_declaration_reaches_the_action_metadata() -> None:
    idempotency = Idempotency(**IDEMPOTENCY)  # type: ignore[arg-type]

    @action(effect=Mutating(idempotency=idempotency))
    async def run() -> None:
        pass

    metadata = get_action_metadata(run)
    assert metadata is not None
    assert (metadata.effect, metadata.verifier, metadata.idempotency) == ("mutating", None, idempotency)
