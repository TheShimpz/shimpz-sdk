"""Tests for the displayed static copy that joins the message catalog."""

import hashlib
import tomllib
from pathlib import Path

import pytest
from shimpz._catalog import DisplayCopy, load_catalog
from shimpz._extract_call import ExtractionError
from shimpz._protocol.message_catalog import display_error, display_uses

SUMMARY = "Manage DNS records."
DESCRIPTION = "Lists your zones and creates or deletes DNS records after you approve each change."
ACTION = 'from shimpz import action, domain, text\n\n\n@action(description={description!r})\nasync def run() -> None:\n'


def catalog(tmp_path: Path, copy: DisplayCopy, *descriptions: str, body: str = "    pass\n") -> dict[str, dict]:
    actions = tmp_path / "actions"
    actions.mkdir(exist_ok=True)
    files = []
    for index, description in enumerate(descriptions):
        path = actions / f"action_{index}.py"
        path.write_text(ACTION.format(description=description) + body, encoding="utf-8")
        files.append(path)
    messages = load_catalog(tmp_path, files, copy).messages
    labels = [label for _, label in copy.labels]
    assert display_error(messages, display_uses(copy.description, descriptions, labels)) is None
    return {message["msgid"]: message for message in messages}


def test_catalogs_the_description_each_action_description_and_each_label(tmp_path: Path) -> None:
    copy = DisplayCopy(SUMMARY, DESCRIPTION, (("api-token", "API token"), ("app-secret", "App secret")))

    messages = catalog(tmp_path, copy, "List your DNS zones.", "Delete one DNS record.")

    assert {msgid: message["max_length"] for msgid, message in messages.items()} == {
        SUMMARY: 80,
        DESCRIPTION: 500,
        "List your DNS zones.": 120,
        "Delete one DNS record.": 120,
        "API token": 120,
        "App secret": 120,
    }
    assert messages[DESCRIPTION] == {
        "id": hashlib.sha256(DESCRIPTION.encode()).hexdigest(),
        "msgid": DESCRIPTION,
        "max_length": 500,
        "params": [],
    }


def test_a_stored_input_description_stays_outside_the_catalog(tmp_path: Path) -> None:
    manifest = tomllib.loads(
        f'[shimpz]\nsummary = "{SUMMARY}"\ndescription = "{DESCRIPTION}"\n\n'
        '[stored_inputs.api-token]\nkind = "password"\nlabel = "API token"\n'
        'description = "Token used to call the provider."\n'
    )
    copy = DisplayCopy.from_manifest(manifest)

    assert copy == DisplayCopy(SUMMARY, DESCRIPTION, (("api-token", "API token"),))
    assert "Token used to call the provider." not in catalog(tmp_path, copy, "List your DNS zones.")


@pytest.mark.parametrize(
    ("copy", "descriptions", "shared", "bound"),
    [
        (DisplayCopy(SUMMARY, DESCRIPTION, (("api-token", SUMMARY),)), ("List zones.",), SUMMARY, 80),
        (DisplayCopy(SUMMARY, DESCRIPTION, (("api-token", "List zones."),)), ("List zones.",), "List zones.", 120),
        (DisplayCopy(SUMMARY, "List zones.", ()), ("List zones.",), "List zones.", 120),
        (DisplayCopy(SUMMARY, SUMMARY, ()), (SUMMARY,), SUMMARY, 80),
    ],
)
def test_one_text_with_several_uses_takes_the_tightest_bound(
    tmp_path: Path, copy: DisplayCopy, descriptions: tuple[str, ...], shared: str, bound: int
) -> None:
    messages = catalog(tmp_path, copy, *descriptions)

    assert messages[shared]["max_length"] == bound
    assert len([message for message in messages.values() if message["msgid"] == shared]) == 1


def test_a_request_copy_message_shared_with_a_label_keeps_the_tighter_bound(tmp_path: Path) -> None:
    copy = DisplayCopy(SUMMARY, DESCRIPTION, (("api-token", "API token"),))
    body = '    text("API token", max_length=500)\n'

    assert catalog(tmp_path, copy, "List zones.", body=body)["API token"]["max_length"] == 120


@pytest.mark.parametrize(
    ("copy", "descriptions", "location"),
    [
        (DisplayCopy("Manage {zone}.", DESCRIPTION), ("List zones.",), r"shimpz\.toml summary"),
        (DisplayCopy(SUMMARY, "Manage {zone} records."), ("List zones.",), r"shimpz\.toml description"),
        (DisplayCopy(SUMMARY, DESCRIPTION, (("api-token", "Token {x}"),)), ("List zones.",), r"api-token\.label"),
        (DisplayCopy(SUMMARY, DESCRIPTION), ("List {zone} records.",), r"actions/action_0\.py:4"),
        (DisplayCopy(SUMMARY, DESCRIPTION), ("List }} records.",), r"actions/action_0\.py:4"),
    ],
)
def test_refuses_braces_in_displayed_copy_with_its_location(
    tmp_path: Path, copy: DisplayCopy, descriptions: tuple[str, ...], location: str
) -> None:
    with pytest.raises(ExtractionError, match=f"{location}: displayed copy takes no parameters, so braces are refused"):
        catalog(tmp_path, copy, *descriptions)


def test_refuses_display_text_that_is_not_nfc_with_its_location(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match=r"shimpz\.toml description: message template must be NFC-normalized"):
        catalog(tmp_path, DisplayCopy(SUMMARY, "Cafe\u0301 records."), "List zones.")
