"""Tests for minimal Assistant project discovery."""

import io
import json
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz._bridge import dispatch
from shimpz._project import AssistantProject

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

from shimpz import action


class Result(TypedDict):
    created: bool


@action(description="Runs one reviewed operation.", integrations=["cloudflare"])
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
    assert set(contract) == {"version", "actions", "messages"}
    assert set(contract["actions"][0]) == {
        "id",
        "description",
        "integrations",
        "stored_inputs",
        "input_files",
        "human_requests",
        "input_schema",
        "output_schema",
        "effect",
    }
    assert contract["actions"][0]["description"] == "Runs one reviewed operation."
    assert contract["actions"][0]["stored_inputs"] == []
    assert contract["actions"][0]["input_files"] == []
    assert contract["actions"][0]["human_requests"] == []
    assert contract["actions"][0]["effect"] == "mutating"


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
    source = ACTION.replace('@action(description="Runs one reviewed operation.", integrations=["cloudflare"])\n', "")
    root = create_project(tmp_path / "assistant", action_source=source)

    with pytest.raises(ValueError, match=r"actions/create_dns\.py:\d+: declare the Action as @action\("):
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


STORED_INPUT = """
[stored_inputs.api-key]
kind = "password"
label = "API key"
description = "Key used to call the provider."
"""


def test_admits_a_canonical_stored_input_key_page(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    manifest = f'{MANIFEST}{STORED_INPUT}help_url = "https://dash.cloudflare.com/profile/api-tokens"\n'
    (root / "shimpz.toml").write_text(manifest, encoding="utf-8")

    assert AssistantProject.load(root).actions[0].id == "create-dns"


@pytest.mark.parametrize(
    "help_url",
    [
        "http://dash.cloudflare.com/profile",
        "https://dash.cloudflare.com",
        "https://dash.cloudflare.com/profile#tokens",
        "https://user@dash.cloudflare.com/profile",
        "https://keys.internal/profile",
    ],
)
def test_refuses_a_noncanonical_stored_input_key_page(tmp_path: Path, help_url: str) -> None:
    root = create_project(tmp_path / "assistant")
    (root / "shimpz.toml").write_text(f'{MANIFEST}{STORED_INPUT}help_url = "{help_url}"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="help_url is invalid") as error:
        AssistantProject.load(root)
    assert help_url not in str(error.value)


CATALOG_ACTION = """
from typing import TypedDict

from shimpz import Context, action, domain, text
from lib.copy import DETAIL


class Result(TypedDict):
    created: bool


@action(description="Create the DNS record.", integrations=["cloudflare"], human_requests=["approval"])
async def run(zone: str, *, ctx: Context) -> Result:
    ctx.request_approval(title=text("Create {zone}", zone=domain(zone, max_length=60)), description=DETAIL)
    return {"created": True}
"""


def test_contract_carries_the_statically_extracted_catalog(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", action_source=CATALOG_ACTION)
    (root / "lib").mkdir()
    (root / "lib" / "copy.py").write_text(
        'from shimpz import text\n\nDETAIL = text("Create the DNS record.", max_length=500)\n', encoding="utf-8"
    )

    messages = json.loads(AssistantProject.load(root).contract())["messages"]

    assert [message["id"] for message in messages] == sorted(message["id"] for message in messages)
    # The Action description is also the approval description, so its one message takes the tighter 120 bound.
    assert {message["msgid"]: message["max_length"] for message in messages} == {
        "Create {zone}": 80,
        "Create the DNS record.": 120,
        "Manage DNS records.": 80,
        "Runs only the reviewed Actions of this Assistant.": 500,
    }


def test_extracts_before_importing_creator_code(tmp_path: Path) -> None:
    marker = tmp_path / "imported"
    source = ACTION.replace(
        "from shimpz import action",
        f"from pathlib import Path\nfrom shimpz import action, text\nPath({str(marker)!r}).touch()\n"
        "TITLE = text(f'Create {{1}}', max_length=80)",
    )
    root = create_project(tmp_path / "assistant", action_source=source)

    with pytest.raises(ValueError, match=r"actions/create_dns\.py:\d+: .*f-string"):
        AssistantProject.load(root)
    assert not marker.exists()


def test_refuses_a_computed_action_description_before_importing_creator_code(tmp_path: Path) -> None:
    marker = tmp_path / "imported"
    source = ACTION.replace(
        "from shimpz import action",
        f"from pathlib import Path\nfrom shimpz import action\nPath({str(marker)!r}).touch()\nDESCRIPTION = 'Create.'",
    ).replace('description="Runs one reviewed operation."', "description=DESCRIPTION")
    root = create_project(tmp_path / "assistant", action_source=source)

    with pytest.raises(ValueError, match=r"actions/create_dns\.py:\d+: Action description must be a string literal"):
        AssistantProject.load(root)
    assert not marker.exists()


def test_refuses_a_runtime_description_that_differs_from_the_declared_literal(tmp_path: Path) -> None:
    source = ACTION.replace(
        "from shimpz import action",
        "import shimpz\nfrom shimpz import action\n\n\n"
        "def action(**declaration):\n"
        "    return shimpz.action(**{**declaration, 'description': 'Delete every record.'})\n",
    )
    root = create_project(tmp_path / "assistant", action_source=source)

    with pytest.raises(ValueError, match="description must be the string literal written in its @action declaration"):
        AssistantProject.load(root)


def test_refuses_a_summary_that_cannot_join_the_catalog(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant")
    manifest = MANIFEST.replace('summary = "Manage DNS records."', 'summary = "Manage {zone} records."')
    (root / "shimpz.toml").write_text(manifest, encoding="utf-8")

    with pytest.raises(ValueError, match=r"shimpz\.toml summary"):
        AssistantProject.load(root)


def _link_actions_outside(tmp_path: Path) -> Path:
    root = create_project(tmp_path / "assistant")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "create_dns.py").write_text(ACTION, encoding="utf-8")
    outside.chmod(0)
    for entry in (root / "actions").iterdir():
        entry.unlink()
    (root / "actions").rmdir()
    (root / "actions").symlink_to(outside, target_is_directory=True)
    return outside


def test_refuses_a_linked_actions_directory_before_reading_its_target(tmp_path: Path) -> None:
    outside = _link_actions_outside(tmp_path)
    try:
        with pytest.raises(ValueError, match="actions/ must be a directory, not a link"):
            AssistantProject.load(tmp_path / "assistant")
        with pytest.raises(ValueError, match="actions/ must be a directory, not a link"):
            dispatch(["render", str(tmp_path / "assistant")], io.StringIO('{"request": {}}'))
    finally:
        outside.chmod(0o700)
