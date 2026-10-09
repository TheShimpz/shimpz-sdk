"""Tests for the static extraction of each Action's ``description=``."""

from pathlib import Path

import pytest
from shimpz._catalog import load_catalog
from shimpz._extract_call import ExtractionError

SUMMARY = "Publish DNS changes."
BODY = "async def run() -> None:\n    pass\n"


def descriptions(tmp_path: Path, source: str) -> dict[str, str]:
    actions = tmp_path / "actions"
    actions.mkdir(exist_ok=True)
    action_file = actions / "list_zones.py"
    action_file.write_text(source, encoding="utf-8")
    extracted = load_catalog(tmp_path, [action_file], SUMMARY).descriptions
    return {path.name: text for path, text in extracted.items()}


def refused(tmp_path: Path, source: str, match: str) -> str:
    with pytest.raises(ExtractionError, match=match) as error:
        descriptions(tmp_path, source)
    message = str(error.value)
    assert message.startswith("actions/list_zones.py:")
    return message


@pytest.mark.parametrize(
    "source",
    [
        'from shimpz import action\n\n\n@action(description="List your DNS zones.")\n' + BODY,
        'import shimpz\n\n\n@shimpz.action(description="List your DNS zones.", effect="read_only")\n' + BODY,
        'from shimpz import action\n\n\n@action(\n    effect="read_only",\n    description="List your " "DNS zones.",\n)\n'
        + BODY,
    ],
)
def test_extracts_the_literal_description_of_each_action_file(tmp_path: Path, source: str) -> None:
    assert descriptions(tmp_path, source) == {"list_zones.py": "List your DNS zones."}


def test_admits_a_description_of_exactly_80_characters_outside_the_bmp(tmp_path: Path) -> None:
    description = "\U0001f600" * 80
    source = f"from shimpz import action\n\n\n@action(description={description!r})\n" + BODY

    assert descriptions(tmp_path, source) == {"list_zones.py": description}


@pytest.mark.parametrize(
    ("decorator", "match"),
    [
        ('@action(description=f"List {zone}.")', "not an f-string"),
        ("@action(description=DESCRIPTION)", "names, concatenation, and computed values are refused"),
        ('@action(description="List " + "zones.")', "names, concatenation, and computed values are refused"),
        ('@action(description=str("List zones."))', "names, concatenation, and computed values are refused"),
        ('@action(description="List zones.".upper())', "names, concatenation, and computed values are refused"),
        ("@action(description=None)", "names, concatenation, and computed values are refused"),
        ("@action(integrations=[])", 'requires description="..."'),
        ('@action(**{"description": "List zones."})', r"\*\*mappings are refused"),
        ("@action", 'must be called with description="..."'),
        (f'@action(description="{"a" * 81}")', "1 to 80 characters"),
        ('@action(description=" List zones.")', "1 to 80 characters"),
        ('@action(description="")', "1 to 80 characters"),
        ('@action(description="Café zones.")', "1 to 80 characters"),
        ('@action(description="List\\u200bzones.")', "1 to 80 characters"),
    ],
)
def test_refuses_a_description_that_is_not_one_literal_line(tmp_path: Path, decorator: str, match: str) -> None:
    source = f'from shimpz import action\n\nDESCRIPTION = "List zones."\n\n\n{decorator}\n' + BODY

    refused(tmp_path, source, match)


@pytest.mark.parametrize(
    "source",
    [
        'from shimpz import action as declare\n\n\n@declare(description="List zones.")\n' + BODY,
        'import shimpz as sz\n\n\n@sz.action(description="List zones.")\n' + BODY,
        'from shimpz.action import action\n\n\n@action(description="List zones.")\n' + BODY,
        'from shimpz import action\n\ndeclare = action\n\n\n@declare(description="List zones.")\n' + BODY,
        "from shimpz import action\n\n\n" + BODY,
        'import shimpz\n\nif True:\n\n    @shimpz.action(description="List zones.")\n    ' + BODY.replace("\n    ", "\n        "),
    ],
)
def test_refuses_an_action_not_declared_directly_on_a_module_level_run(tmp_path: Path, source: str) -> None:
    refused(tmp_path, source, r"declare the Action as @action\(description=")


def test_refuses_two_module_level_run_definitions(tmp_path: Path) -> None:
    declared = '@action(description="List zones.")\n' + BODY
    source = "from shimpz import action\n\n\n" + declared + "\n\n" + declared

    assert refused(tmp_path, source, "declare the Action").startswith("actions/list_zones.py:10:")


def test_library_modules_declare_no_action(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")
    source = 'from shimpz import action\n\n\n@action(description="List zones.")\n' + BODY

    assert descriptions(tmp_path, source) == {"list_zones.py": "List zones."}
