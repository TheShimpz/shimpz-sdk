"""Tests for minimal Assistant project discovery."""

import json
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz._project import AssistantProject

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

from shimpz import action


class Result(TypedDict):
    created: bool


@action(integrations=["cloudflare"])
async def run(zone: str) -> Result:
    return {"created": True}
"""


def create_project(root: Path, *, action_name: str = "create_dns.py", action_source: str = ACTION) -> Path:
    root.mkdir()
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    actions = root / "actions"
    actions.mkdir()
    (actions / action_name).write_text(action_source, encoding="utf-8")
    return root


def test_discovers_one_action_per_python_file(tmp_path: Path) -> None:
    project = AssistantProject.load(create_project(tmp_path / "assistant"))

    assert project.actions[0].id == "create-dns"
    assert project.actions[0].integrations == ("cloudflare",)

    contract = json.loads(project.contract())

    assert contract["version"] == 1
    assert set(contract["actions"][0]) == {
        "id",
        "integrations",
        "human_requests",
        "input_schema",
        "output_schema",
    }
    assert contract["actions"][0]["human_requests"] == []


def test_loads_optional_project_lib_modules(tmp_path: Path) -> None:
    root = create_project(
        tmp_path / "assistant",
        action_source=ACTION.replace("return {", "from lib.value import CREATED\n    return {").replace(
            "True}", "CREATED}"
        ),
    )
    library = root / "lib"
    library.mkdir()
    (library / "value.py").write_text("CREATED = True\n", encoding="utf-8")

    project = AssistantProject.load(root)

    assert project.actions[0].id == "create-dns"


def test_requires_the_actions_directory(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    root.mkdir()
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")

    with pytest.raises(ValueError, match="actions/ is required"):
        AssistantProject.load(root)


def test_requires_pyproject_for_a_publishable_source_tree(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    (root / "pyproject.toml").unlink(missing_ok=True)

    with pytest.raises(ValueError, match="missing_required_file"):
        AssistantProject.load(root)


def test_requires_a_canonical_icon_for_a_publishable_source_tree(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    (root / "icon.png").unlink()

    with pytest.raises(ValueError, match="missing_required_file"):
        AssistantProject.load(root)


def test_rejects_a_malformed_canonical_icon(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    (root / "icon.png").write_bytes(b"not a PNG")

    with pytest.raises(ValueError, match="invalid_icon"):
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

    assert project.actions[0].id == "create-dns"


def test_rejects_non_snake_case_action_files(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", action_name="CreateDns.py")

    with pytest.raises(ValueError, match="invalid entry"):
        AssistantProject.load(root)


def test_requires_a_decorated_run(tmp_path: Path) -> None:
    source = ACTION.replace('@action(integrations=["cloudflare"])\n', "")
    root = create_project(tmp_path / "assistant", action_source=source)

    with pytest.raises(ValueError, match="@action async def run"):
        AssistantProject.load(root)


def test_reports_the_source_of_an_unsupported_parameter_annotation(tmp_path: Path) -> None:
    source = ACTION.replace("zone: str", "zone: dict[str, str]")
    root = create_project(tmp_path / "assistant", action_source=source)

    with pytest.raises(TypeError) as failure:
        AssistantProject.load(root)

    assert str(failure.value) == (
        "actions/create_dns.py:12: unsupported Action type annotation: parameter 'zone' uses dict[str, str]"
    )


def test_reports_the_source_of_an_unsupported_typed_dict_field(tmp_path: Path) -> None:
    source = ACTION.replace("created: bool", "created: dict[str, str]")
    root = create_project(tmp_path / "assistant", action_source=source)

    with pytest.raises(TypeError) as failure:
        AssistantProject.load(root)

    assert str(failure.value) == (
        "actions/create_dns.py:8: unsupported Action type annotation: field 'created' uses dict[str, str]"
    )
