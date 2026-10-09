"""Tests for local validated Action execution."""

import asyncio
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz._project import AssistantProject
from shimpz._runtime import ActionFailure, ActionInvocation, invoke_action

OPERATION_ID = "6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"

MANIFEST = """
[shimpz]
spec = 1
id = "shimpz-cloudflare"
version = "0.1.0"
name = "Cloudflare"
summary = "Manage DNS records."
description = "Runs only the reviewed Actions of this Assistant."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/shimpz-cloudflare"
genesis = "Manage Cloudflare safely."

[network]
allowed_hosts = ["api.cloudflare.com"]

[integrations.cloudflare]
scopes = ["dns:write"]
"""

ACTION = """
from typing import TypedDict

from shimpz import Context, action


class Result(TypedDict):
    zone_length: int


@action(description="Runs one reviewed operation.", integrations=["cloudflare"])
async def run(zone: str, *, ctx: Context) -> Result:
    return {"zone_length": len(zone)}
"""


def project_at(root: Path, source: str = ACTION) -> AssistantProject:
    root.mkdir()
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    actions = root / "actions"
    actions.mkdir()
    (actions / "inspect_dns.py").write_text(source, encoding="utf-8")
    return AssistantProject.load(root)


def test_invokes_with_validated_inputs(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    result = asyncio.run(
        invoke_action(
            project,
            "inspect-dns",
            ActionInvocation(
                inputs={"zone": "example.com"},
                stored_inputs=(),
                operation_id=OPERATION_ID,
            ),
        )
    )

    assert result == {"zone_length": 11}


def test_rejects_an_undeclared_stored_input(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    with pytest.raises(ValueError, match="Stored Inputs"):
        asyncio.run(
            invoke_action(
                project,
                "inspect-dns",
                ActionInvocation(
                    inputs={"zone": "example.com"},
                    stored_inputs=("api-token",),
                    operation_id=OPERATION_ID,
                ),
            )
        )


def test_validates_input_before_execution(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    with pytest.raises(ValueError, match="input"):
        asyncio.run(
            invoke_action(
                project,
                "inspect-dns",
                ActionInvocation(
                    inputs={"zone": 42},
                    stored_inputs=(),
                    operation_id=OPERATION_ID,
                ),
            )
        )


def test_redacts_action_exceptions(tmp_path: Path) -> None:
    source = ACTION.replace(
        'return {"zone_length": len(zone)}',
        'ctx.register_secret("private-token")\n    raise RuntimeError("private-token")',
    )
    project = project_at(tmp_path / "assistant", source)

    with pytest.raises(ActionFailure, match="Action failed") as captured:
        asyncio.run(
            invoke_action(
                project,
                "inspect-dns",
                ActionInvocation(
                    inputs={"zone": "example.com"},
                    stored_inputs=(),
                    operation_id=OPERATION_ID,
                ),
            )
        )

    assert "private-token" not in str(captured.value)
    assert captured.value.envelope == {
        "type": "failure",
        "failure": {
            "error_type": "RuntimeError",
            "message": "[REDACTED]",
            "provider": None,
            "http_status": None,
            "response_excerpt": None,
            "redacted": True,
            "truncated": False,
        },
    }
