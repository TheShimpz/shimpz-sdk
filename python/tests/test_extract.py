"""Tests for the static message catalog extractor."""

import hashlib
from pathlib import Path

import pytest
from shimpz._catalog import load_catalog
from shimpz._extract_call import ExtractionError

SUMMARY = "Publish DNS changes."
HEADER = "from shimpz import Context, InputOption, InputRequest, action, domain, identifier, integer, text\n"


def catalog(tmp_path: Path, source: str, *, lib: str | None = None, summary: str = SUMMARY) -> list[dict]:
    actions = tmp_path / "actions"
    actions.mkdir(exist_ok=True)
    action_file = actions / "publish.py"
    action_file.write_text(source, encoding="utf-8")
    if lib is not None:
        (tmp_path / "lib").mkdir(exist_ok=True)
        (tmp_path / "lib" / "copy.py").write_text(lib, encoding="utf-8")
    return load_catalog(tmp_path, [action_file], summary)


def refused(tmp_path: Path, source: str, match: str, **options: str) -> str:
    with pytest.raises(ExtractionError, match=match) as error:
        catalog(tmp_path, source, **options)
    return str(error.value)


def by_msgid(messages: list[dict]) -> dict[str, dict]:
    return {message["msgid"]: message for message in messages}


def test_extracts_request_copy_with_field_bounds_and_the_summary(tmp_path: Path) -> None:
    source = HEADER + (
        "ctx.request_approval(\n"
        '    title=text("Publish {count} changes", count=integer(n, digits=4)),\n'
        '    description=text("Publish to {zone}.", zone=domain(zone, max_length=60)),\n'
        ")\n"
        'ctx.request_auth("passkey", title=text("Authorize"), description=text("Confirm the change."))\n'
        'InputRequest("choice", text("Mode"), text("Choose a mode."), text("Mode"), text("Pick one"),\n'
        '    options=(InputOption("safe", text("Safe"), text("Prefer the safest route.")),\n'
        '             InputOption(value="fast", label=text("Fast"), description=None)))\n'
        'InputRequest(kind="text", title=text("Zone"), description=text("Zone id {id}", id=identifier(i, max_length=32)),\n'
        '    label=text("Zone"), placeholder=text("example.com"))\n'
    )

    messages = by_msgid(catalog(tmp_path, source))

    assert messages["Publish {count} changes"] == {
        "id": hashlib.sha256(b"Publish {count} changes").hexdigest(),
        "msgid": "Publish {count} changes",
        "max_length": 80,
        "params": [{"name": "count", "kind": "integer", "max_length": 4}],
    }
    assert messages["Publish to {zone}."]["max_length"] == 500
    assert messages["Publish to {zone}."]["params"] == [{"name": "zone", "kind": "domain", "max_length": 60}]
    assert messages["Zone id {id}"]["params"] == [{"name": "id", "kind": "identifier", "max_length": 32}]
    assert messages["Prefer the safest route."]["max_length"] == 160
    assert messages["Pick one"]["max_length"] == 120
    assert messages["example.com"]["max_length"] == 120
    assert messages["Mode"]["max_length"] == 80
    assert messages[SUMMARY] == {
        "id": hashlib.sha256(SUMMARY.encode()).hexdigest(),
        "msgid": SUMMARY,
        "max_length": 160,
        "params": [],
    }
    ids = [message["id"] for message in messages.values()]
    assert [message["id"] for message in catalog(tmp_path, source)] == sorted(ids)


def test_uses_the_smallest_field_bound_and_an_explicit_bound_elsewhere(tmp_path: Path) -> None:
    source = HEADER + (
        'COPY = text("Delete the record.", max_length=160)\n'
        'ctx.request_approval(title=text("Delete the record."), description=text("Delete the record."))\n'
        'ctx.request_approval(title=text("Delete", max_length=80), description=COPY)\n'
    )

    messages = by_msgid(catalog(tmp_path, source))

    assert messages["Delete the record."]["max_length"] == 80
    assert messages["Delete"]["max_length"] == 80


def test_scans_lib_modules_and_the_module_import_form(tmp_path: Path) -> None:
    lib = 'import shimpz\n\nDELETE = shimpz.text("Delete {zone}", zone=shimpz.domain(z, max_length=40), max_length=500)\n'

    messages = by_msgid(catalog(tmp_path, "print('no copy')\n", lib=lib))

    assert messages["Delete {zone}"]["max_length"] == 500


def test_ignores_unrelated_text_names_and_annotation_only_fields(tmp_path: Path) -> None:
    unrelated = "def text(value):\n    return value\n\ntext(compute())\n"
    assert by_msgid(catalog(tmp_path, unrelated)).keys() == {SUMMARY}

    field = HEADER + "from typing import TypedDict\n\nclass Result(TypedDict):\n    text: str\n"
    assert by_msgid(catalog(tmp_path, field)).keys() == {SUMMARY}


@pytest.mark.parametrize(
    ("source", "match"),
    [
        ("TEMPLATE = 'Zone'\nctx.request_approval(title=text(TEMPLATE), description=text('D'))\n", "string literal"),
        ("ctx.request_approval(title=text(f'Zone {zone}'), description=text('D'))\n", "f-string"),
        ("ctx.request_approval(title=text('Zone ' + 'x'), description=text('D'))\n", "computed"),
        ("ctx.request_approval(title=text('A', 'B'), description=text('D'))\n", "one positional"),
        ("ctx.request_approval(title=text(*parts), description=text('D'))\n", "one positional"),
        ("ctx.request_approval(title=text('Zone {zone}', zone=zone), description=text('D'))\n", "shimpz.domain"),
        ("ctx.request_approval(title=text('Zone {zone}', **params), description=text('D'))\n", "keyword arguments"),
        ("ctx.request_approval(title=text('Zone {zone}', zone=text('x')), description=text('D'))\n", "shimpz.domain"),
        ("x = text('Zone')\n", "requires a literal max_length"),
        ("[text('Zone') for _ in range(2)]\n", "requires a literal max_length"),
        ("x = text('Zone', max_length=limit)\n", "integer literal"),
        ("x = text('Zone', max_length=100)\n", "80, 120, 160, or 500"),
        ("ctx.request_approval(title=text('Zone', max_length=500), description=text('D'))\n", "exceeds the 80"),
        ("x = text('N {n}', n=integer(n), max_length=80)\n", "requires a literal digits"),
        ("x = text('N {n}', n=integer(n, digits=width), max_length=80)\n", "integer literal"),
        ("x = text('N {n}', n=integer(n, digits=16), max_length=80)\n", "from 1 to 15"),
        ("x = text('Id {n}', n=identifier(n), max_length=80)\n", "requires a literal max_length"),
        ("x = text('Id {n}', n=identifier(n, max_length=8, extra=1), max_length=80)\n", "accepts only"),
        ("x = text('Zone {z}', z=domain(z), max_length=80)\n", "does not fit its 80-character"),
        ("n = integer(3, digits=1)\n", "directly as a text"),
        ("t = text\n", "called directly"),
        ("def build(text):\n    return text\n", "rebinding 'text'"),
        (
            "prefix = ['text', text('T', max_length=80)]\nInputRequest(*prefix, text('D'), text('L'))\n",
            r"after \*args",
        ),
        ("InputOption(*values, text('Safe'))\n", r"after \*args"),
        ("text = None\n", "rebinding 'text'"),
    ],
)
def test_refuses_unsupported_calls_with_a_source_location(tmp_path: Path, source: str, match: str) -> None:
    message = refused(tmp_path, HEADER + source, match)

    assert message.startswith("actions/publish.py:")


@pytest.mark.parametrize(
    ("source", "match"),
    [
        ("from shimpz import text as t\n", "without an alias"),
        ("import shimpz as sz\n", "without an alias"),
        ("from shimpz import *\n", "without an alias"),
        ("from shimpz.message import text\n", "from shimpz import"),
        ("from lib.copy import text\n", "from shimpz import"),
        ("from .copy import text\n", "from shimpz import"),
        ("import shimpz.message\nx = shimpz.message.text('Zone', max_length=80)\n", "call shimpz.text directly"),
        ("from shimpz import text\nimport json as text\n", "rebinding 'text'"),
    ],
)
def test_refuses_aliases_and_re_exports(tmp_path: Path, source: str, match: str) -> None:
    refused(tmp_path, source, match)


@pytest.mark.parametrize(
    ("template", "match"),
    [
        ("Café", "NFC"),
        (" Zone", "trimmed printable"),
        ("Zone​", "trimmed printable"),
        ("Zone {{zone}}", "fields only"),
        ("Zone {0}", "fields only"),
        ("Zone {}", "fields only"),
        ("Zone {zone!r}", "fields only"),
        ("Zone {zone:>10}", "fields only"),
        ("Zone {zone.name}", "fields only"),
        ("Zone {zone[0]}", "fields only"),
        ("Zone {zone{inner}}", "fields only"),
        ("Zone {zone} and {zone}", "each appear once"),
        ("Zone {other}", "match the text"),
        ("Zone {zone}́", "combining mark"),
    ],
)
def test_refuses_invalid_templates(tmp_path: Path, template: str, match: str) -> None:
    source = HEADER + f"x = text({template!r}, zone=domain(z, max_length=20), max_length=500)\n"

    message = refused(tmp_path, source, match)

    assert message.startswith("actions/publish.py:2:")


def test_refuses_conflicting_declarations_and_an_invalid_summary(tmp_path: Path) -> None:
    conflicting = HEADER + (
        "a = text('N {n}', n=integer(n, digits=2), max_length=80)\n"
        "b = text('N {n}', n=integer(n, digits=3), max_length=80)\n"
    )
    assert "other parameters at actions/publish.py:2" in refused(tmp_path, conflicting, "declared with")

    with pytest.raises(ExtractionError, match=r"shimpz\.toml summary: message placeholders"):
        catalog(tmp_path, HEADER, summary="Publish {zone}.")


def test_refuses_an_unparseable_source_with_its_location(tmp_path: Path) -> None:
    refused(tmp_path, "def broken(:\n", r"actions/publish.py:1: source cannot be parsed")
