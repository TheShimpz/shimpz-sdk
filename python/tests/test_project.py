"""Tests for minimal Assistant project discovery."""

import json
from pathlib import Path

import pytest
from shimpz._project import AssistantProject

MANIFEST = """
spec = 1
id = "shimpz-cloudflare"
version = "0.1.0"
name = "Cloudflare"
summary = "Manage DNS records."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/shimpz-cloudflare"
allowed_hosts = ["api.cloudflare.com"]
genesis = "Manage Cloudflare safely."

[integrations.cloudflare]
scopes = ["dns:write"]
"""

POWER = """
from typing import TypedDict

from shimpz import power


class Result(TypedDict):
    created: bool


@power(integrations=["cloudflare"])
async def run(zone: str) -> Result:
    return {"created": True}
"""


def create_project(root: Path, *, power_name: str = "create_dns.py", power_source: str = POWER) -> Path:
    root.mkdir()
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    powers = root / "powers"
    powers.mkdir()
    (powers / power_name).write_text(power_source, encoding="utf-8")
    return root


def test_discovers_one_power_per_python_file(tmp_path: Path) -> None:
    project = AssistantProject.load(create_project(tmp_path / "assistant"))

    assert project.powers[0].id == "create-dns"
    assert project.powers[0].integrations == ("cloudflare",)

    contract = json.loads(project.contract())

    assert contract["version"] == 1
    assert set(contract["powers"][0]) == {
        "id",
        "integrations",
        "input_schema",
        "output_schema",
    }


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


def test_requires_pyproject_for_a_publishable_source_tree(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    (root / "pyproject.toml").unlink(missing_ok=True)

    with pytest.raises(ValueError, match="missing_required_file"):
        AssistantProject.load(root)


def test_rejects_links_inside_publishable_source_directories(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    library = root / "lib"
    library.mkdir()
    (library / "outside.py").symlink_to(tmp_path / "outside.py")

    with pytest.raises(ValueError, match="special_file"):
        AssistantProject.load(root)


def test_ignores_local_root_files_outside_the_source_allowlist(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    (root / "README.md").write_text("Local notes.\n", encoding="utf-8")

    project = AssistantProject.load(root)

    assert project.powers[0].id == "create-dns"


def test_rejects_non_snake_case_power_files(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", power_name="CreateDns.py")

    with pytest.raises(ValueError, match="invalid entry"):
        AssistantProject.load(root)


def test_requires_a_decorated_run(tmp_path: Path) -> None:
    source = POWER.replace('@power(integrations=["cloudflare"])\n', "")
    root = create_project(tmp_path / "assistant", power_source=source)

    with pytest.raises(ValueError, match="@power async def run"):
        AssistantProject.load(root)


def test_reports_the_source_of_an_unsupported_parameter_annotation(tmp_path: Path) -> None:
    source = POWER.replace("zone: str", "zone: dict[str, str]")
    root = create_project(tmp_path / "assistant", power_source=source)

    with pytest.raises(TypeError) as failure:
        AssistantProject.load(root)

    assert str(failure.value) == (
        "powers/create_dns.py:12: unsupported Power type annotation: parameter 'zone' uses dict[str, str]"
    )


def test_reports_the_source_of_an_unsupported_typed_dict_field(tmp_path: Path) -> None:
    source = POWER.replace("created: bool", "created: dict[str, str]")
    root = create_project(tmp_path / "assistant", power_source=source)

    with pytest.raises(TypeError) as failure:
        AssistantProject.load(root)

    assert str(failure.value) == (
        "powers/create_dns.py:8: unsupported Power type annotation: field 'created' uses dict[str, str]"
    )
