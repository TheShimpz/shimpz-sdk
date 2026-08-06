"""Tests for the Power subprocess result boundary."""

import contextlib
import json
import multiprocessing
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from _fixtures import write_icon

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

SYSTEM_EXIT_POWER = """
from typing import TypedDict

from shimpz import power


class Result(TypedDict):
    greeting: str


@power()
async def run(name: str) -> Result:
    print("FORGED-STDOUT-BYTES")
    raise SystemExit(0)
"""

PRINTING_POWER = """
from typing import TypedDict

from shimpz import power


class Result(TypedDict):
    greeting: str


@power()
async def run(name: str) -> Result:
    print("CHATTER-ON-STDOUT")
    return {"greeting": f"Hello, {name}"}
"""


def _project(root: Path, source: str) -> Path:
    root.mkdir()
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    powers = root / "powers"
    powers.mkdir()
    (powers / "act.py").write_text(source, encoding="utf-8")
    return root


@dataclass(frozen=True)
class _Result:
    returncode: int
    stdout: str
    stderr: str


def _run_bridge(root: Path, stdin_path: Path, stdout_path: Path, stderr_path: Path) -> None:
    import shimpz._bridge as bridge

    with (
        stdin_path.open(encoding="utf-8") as stdin,
        stdout_path.open("w", encoding="utf-8") as stdout,
        stderr_path.open("w", encoding="utf-8") as stderr,
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        sys.stdin = stdin
        code = bridge.main(["invoke", str(root), "act"])
    raise SystemExit(code)


def _invoke(root: Path) -> _Result:
    stdin_path = root.parent / "stdin.txt"
    stdout_path = root.parent / "stdout.txt"
    stderr_path = root.parent / "stderr.txt"
    stdin_path.write_text('{"input":{"name":"Ada"},"integrations":{}}', encoding="utf-8")
    process = multiprocessing.get_context("spawn").Process(
        target=_run_bridge,
        args=(root, stdin_path, stdout_path, stderr_path),
    )
    process.start()
    process.join()
    return _Result(
        returncode=process.exitcode or 0,
        stdout=stdout_path.read_text(encoding="utf-8"),
        stderr=stderr_path.read_text(encoding="utf-8"),
    )


def test_system_exit_cannot_forge_stdout(tmp_path: Path) -> None:
    result = _invoke(_project(tmp_path / "assistant", SYSTEM_EXIT_POWER))

    assert result.returncode != 0
    assert "FORGED-STDOUT-BYTES" not in result.stdout


def test_printing_power_returns_only_validated_json(tmp_path: Path) -> None:
    result = _invoke(_project(tmp_path / "assistant", PRINTING_POWER))

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "type": "result",
        "result": {"greeting": "Hello, Ada"},
    }
    assert "CHATTER-ON-STDOUT" not in result.stdout


def test_main_fails_closed_on_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    import shimpz._bridge as bridge

    def abort(_arguments: list[str], _source: object) -> str:
        raise SystemExit(0)

    monkeypatch.setattr(bridge, "dispatch", abort)

    assert bridge.main(["invoke", "x", "y"]) == 1
