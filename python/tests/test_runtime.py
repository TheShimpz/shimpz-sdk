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
    token_length: int


@action(integrations=["cloudflare"])
async def run(zone: str, *, ctx: Context) -> Result:
    return {"token_length": len(ctx.integrations.cloudflare.access_token)}
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


def test_invokes_with_validated_inputs_and_redacted_integrations(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    result = asyncio.run(
        invoke_action(
            project,
            "inspect-dns",
            ActionInvocation(
                inputs={"zone": "example.com"},
                integrations={"cloudflare": "private-token"},
                stored_inputs={},
                operation_id=OPERATION_ID,
            ),
        )
    )

    assert result == {"token_length": 13}
    assert "private-token" not in repr(project.actions)


def test_rejects_missing_integrations(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    with pytest.raises(ValueError, match="integrations"):
        asyncio.run(
            invoke_action(
                project,
                "inspect-dns",
                ActionInvocation(
                    inputs={"zone": "example.com"},
                    integrations={},
                    stored_inputs={},
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
                    integrations={"cloudflare": "private-token"},
                    stored_inputs={},
                    operation_id=OPERATION_ID,
                ),
            )
        )


def test_redacts_action_exceptions(tmp_path: Path) -> None:
    source = ACTION.replace(
        'return {"token_length": len(ctx.integrations.cloudflare.access_token)}',
        "raise RuntimeError(ctx.integrations.cloudflare.access_token)",
    )
    project = project_at(tmp_path / "assistant", source)

    with pytest.raises(ActionFailure, match="Action failed") as captured:
        asyncio.run(
            invoke_action(
                project,
                "inspect-dns",
                ActionInvocation(
                    inputs={"zone": "example.com"},
                    integrations={"cloudflare": "private-token"},
                    stored_inputs={},
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
