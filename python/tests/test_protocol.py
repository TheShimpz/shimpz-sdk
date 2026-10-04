"""Integrity of the reference validators shipped inside the Python package."""

import os
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
        "action_effect.py",
        "failure.py",
        "human_request.py",
        "input_file.py",
        "message_catalog.py",
    ],
)
def test_packaged_validators_are_byte_identical_to_the_pinned_mirror(name: str) -> None:
    assert (PACKAGED / name).read_bytes() == (MIRROR / "validators" / name).read_bytes()


# The pinned upstream verifier opens each artifact with POSIX-only descriptor flags; its byte identity is still pinned on
# every platform by the Rust mirror test, and the vectors still run through the SDK on every platform.
@pytest.mark.skipif(
    not (hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_NONBLOCK")),
    reason="the pinned Assistant Spec verifier needs POSIX descriptor flags",
)
def test_pinned_mirror_verifies_its_artifacts_and_vectors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.syspath_prepend(str(MIRROR))
    for name in [name for name in sys.modules if name == "validators" or name.startswith("validators.")]:
        monkeypatch.delitem(sys.modules, name)

    runpy.run_path(str(MIRROR / "verify.py"), run_name="__main__")

    assert capsys.readouterr().out.strip() == "Assistant protocol artifacts and conformance vectors are valid"
