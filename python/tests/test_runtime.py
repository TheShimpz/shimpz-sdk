"""Tests for local validated Power execution."""

import asyncio
from pathlib import Path

import pytest
from shimpz._project import AssistantProject
from shimpz._runtime import PowerExecutionError, invoke_power

MANIFEST = """
spec = 1
version = "0.1.0"
name = "Cloudflare"
summary = "Manage DNS records."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/shimpz-cloudflare"
allowed_hosts = ["api.cloudflare.com"]
genesis = "Manage Cloudflare safely."

[accounts.cloudflare]
scopes = ["dns:write"]
"""

POWER = """
from typing import TypedDict

from shimpz import Context, power


class Result(TypedDict):
    token_length: int


@power(accounts=["cloudflare"])
async def run(zone: str, *, ctx: Context) -> Result:
    return {"token_length": len(ctx.accounts.cloudflare.access_token)}
"""


def project_at(root: Path, source: str = POWER) -> AssistantProject:
    root.mkdir()
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    powers = root / "powers"
    powers.mkdir()
    (powers / "inspect_dns.py").write_text(source, encoding="utf-8")
    return AssistantProject.load(root)


def test_invokes_with_validated_inputs_and_redacted_accounts(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    result = asyncio.run(
        invoke_power(
            project,
            "inspect-dns",
            {"zone": "example.com"},
            {"cloudflare": "private-token"},
        )
    )

    assert result == {"token_length": 13}
    assert "private-token" not in repr(project.powers)


def test_rejects_missing_accounts(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    with pytest.raises(ValueError, match="accounts"):
        asyncio.run(invoke_power(project, "inspect-dns", {"zone": "example.com"}))


def test_validates_input_before_execution(tmp_path: Path) -> None:
    project = project_at(tmp_path / "assistant")

    with pytest.raises(ValueError, match="input"):
        asyncio.run(
            invoke_power(
                project,
                "inspect-dns",
                {"zone": 42},
                {"cloudflare": "private-token"},
            )
        )


def test_redacts_power_exceptions(tmp_path: Path) -> None:
    source = POWER.replace(
        'return {"token_length": len(ctx.accounts.cloudflare.access_token)}',
        "raise RuntimeError(ctx.accounts.cloudflare.access_token)",
    )
    project = project_at(tmp_path / "assistant", source)

    with pytest.raises(PowerExecutionError, match="Power execution failed") as captured:
        asyncio.run(
            invoke_power(
                project,
                "inspect-dns",
                {"zone": "example.com"},
                {"cloudflare": "private-token"},
            )
        )

    assert "private-token" not in str(captured.value)
