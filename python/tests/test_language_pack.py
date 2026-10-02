"""Tests for the private bridge command that verifies a prepared language pack."""

import io
import json
import sys
from pathlib import Path

import pytest
from shimpz._bridge import dispatch, main
from shimpz._language_pack import PackRefusedError
from shimpz._protocol.message_catalog import (
    LOCALES,
    PACK_FORMAT,
    canonical_json,
    catalog_digest,
    pack_digest,
)
from test_bridge import HUMAN_ACTION, create_project

POLICY = "sha256:" + "c" * 64


def catalog(root: Path) -> list[dict[str, object]]:
    return json.loads(dispatch(["catalog", str(root)], io.StringIO("")))["messages"]


def pack(messages: list[dict[str, object]]) -> dict[str, object]:
    translations = {str(message["id"]): f"«{message['msgid']}»" for message in messages}
    return {
        "catalog": catalog_digest(messages),
        "format": PACK_FORMAT,
        "locales": {locale: dict(translations) for locale in LOCALES},
        "policy": POLICY,
    }


def verify(root: Path, raw: bytes) -> dict[str, str]:
    source = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    return json.loads(dispatch(["verify-pack", str(root)], source))


def test_acknowledges_exactly_the_pack_for_the_static_catalog(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", HUMAN_ACTION)
    messages = catalog(root)
    raw = canonical_json(pack(messages))

    assert verify(root, raw) == {"catalog": catalog_digest(messages), "pack": pack_digest(raw)}


def test_verifies_without_importing_creator_code(tmp_path: Path) -> None:
    marker = tmp_path / "imported"
    source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n" + HUMAN_ACTION
    root = create_project(tmp_path / "assistant", source)

    verify(root, canonical_json(pack(catalog(root))))

    assert not marker.exists()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda value, _: value["locales"]["ja"].popitem(), "pack_incomplete"),
        (lambda value, _: value.update(catalog="sha256:" + "d" * 64), "pack_catalog"),
        (lambda value, _: value["locales"].pop("zh"), "pack_shape"),
        (lambda value, ids: value["locales"]["pt"].update({ids[0]: "Sem marcador"}), "translation_placeholders"),
        (lambda value, ids: value["locales"]["de"].update({ids[0]: "Gruß an {name}́."}), "translation_placeholders"),
        (lambda value, ids: value["locales"]["fr"].update({ids[1]: "Café"}), "public_text"),
    ],
)
def test_refuses_with_the_reference_validator_code_only(tmp_path: Path, mutate, code: str) -> None:
    root = create_project(tmp_path / "assistant", HUMAN_ACTION)
    messages = catalog(root)
    value = pack(messages)
    with_param = [str(message["id"]) for message in messages if message["params"]]
    plain = [str(message["id"]) for message in messages if not message["params"]]
    mutate(value, [*with_param, *plain])

    with pytest.raises(PackRefusedError) as refused:
        verify(root, canonical_json(value))

    assert str(refused.value) == code


def test_reads_exact_bytes_without_newline_translation(tmp_path: Path) -> None:
    root = create_project(tmp_path / "assistant", HUMAN_ACTION)
    raw = canonical_json(pack(catalog(root)))

    for altered, code in (
        (raw + b"\n", "pack_encoding"),
        (raw + b"\r\n", "pack_encoding"),
        (b" " + raw, "pack_encoding"),
        (b"", "pack_encoding"),
        (b" " * (2_097_152 + 1), "pack_bytes"),
    ):
        with pytest.raises(PackRefusedError) as refused:
            verify(root, altered)
        assert str(refused.value) == code


def test_bridge_exits_with_only_the_error_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = create_project(tmp_path / "assistant", HUMAN_ACTION)
    value = pack(catalog(root))

    def run(raw: bytes) -> int:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
        return main(["verify-pack", str(root)])

    assert run(canonical_json(value)) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"catalog", "pack"}
    value["locales"]["ar"].popitem()
    assert run(canonical_json(value)) == 1
    assert capsys.readouterr() == ("", "shimpz: pack_incomplete\n")
