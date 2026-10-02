"""Integrity of the reference validators shipped inside the Python package."""

import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
MIRROR = ROOT / "crates/shimpz-genesis/protocol/assistant/v1"
PACKAGED = ROOT / "python/src/shimpz/_protocol"


@pytest.mark.parametrize(
    "name",
    [
        "action_effect_validator.py",
        "failure_validator.py",
        "human_request_validator.py",
        "input_file_validator.py",
        "message_catalog_validator.py",
    ],
)
def test_packaged_validators_are_byte_identical_to_the_pinned_mirror(name: str) -> None:
    assert (PACKAGED / name).read_bytes() == (MIRROR / name).read_bytes()


def test_pinned_mirror_verifies_its_artifacts_and_vectors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.syspath_prepend(str(MIRROR))
    for name in (
        "action_effect_validator",
        "failure_validator",
        "human_request_validator",
        "input_file_validator",
        "message_catalog_validator",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    runpy.run_path(str(MIRROR / "verify.py"), run_name="__main__")

    assert capsys.readouterr().out.strip() == "Assistant protocol artifacts and conformance vectors are valid"
