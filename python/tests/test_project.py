"""Tests for minimal Assistant project discovery."""

import json
from pathlib import Path

import pytest
from shimpz._project import AssistantProject

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

from shimpz import power


class Result(TypedDict):
    created: bool


@power(accounts=["cloudflare"])
async def run(zone: str) -> Result:
    return {"created": True}
"""


def create_project(root: Path, *, power_name: str = "create_dns.py", power_source: str = POWER) -> Path:
    root.mkdir()
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    powers = root / "powers"
    powers.mkdir()
    (powers / power_name).write_text(power_source, encoding="utf-8")
    return root


def test_discovers_one_power_per_python_file(tmp_path: Path) -> None:
    project = AssistantProject.load(create_project(tmp_path / "assistant"))

    assert project.powers[0].id == "create-dns"
    assert project.powers[0].accounts == ("cloudflare",)

    contract = json.loads(project.contract())

    assert contract["version"] == 1
    assert contract["powers"][0]["path"] == "/v1/powers/create-dns"


def test_loads_optional_project_lib_modules(tmp_path: Path) -> None:
    root = create_project(
        tmp_path / "assistant",
        power_source=POWER.replace("return {", "from lib.value import CREATED\n    return {").replace(
            "True}", "CREATED}"
        ),
    )
    library = root / "lib"
    library.mkdir()
    (library / "value.py").write_text("CREATED = True\n", encoding="utf-8")

    project = AssistantProject.load(root)

    assert project.powers[0].id == "create-dns"


def test_requires_the_powers_directory(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    root.mkdir()
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")

    with pytest.raises(ValueError, match="powers/ is required"):
        AssistantProject.load(root)


def test_rejects_non_snake_case_power_files(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", power_name="CreateDns.py")

    with pytest.raises(ValueError, match="invalid entry"):
        AssistantProject.load(root)


def test_requires_a_decorated_run(tmp_path: Path) -> None:
    source = POWER.replace('@power(accounts=["cloudflare"])\n', "")
    root = create_project(tmp_path / "assistant", power_source=source)

    with pytest.raises(ValueError, match="@power async def run"):
        AssistantProject.load(root)
