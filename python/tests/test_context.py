"""Tests for invocation-scoped Accounts addressing."""

import pytest
from shimpz.context import Accounts


def test_subscript_reaches_a_hyphenated_account_id() -> None:
    value = "opaque-value"
    accounts = Accounts({"cloudflare-api": value})

    assert accounts["cloudflare-api"].access_token == value


def test_attribute_access_reaches_an_identifier_safe_id() -> None:
    value = "opaque-value"
    accounts = Accounts({"cloudflare": value})

    assert accounts.cloudflare.access_token == value


def test_missing_subscript_id_raises_key_error() -> None:
    accounts = Accounts({"cloudflare": "token"})

    with pytest.raises(KeyError, match="was not injected"):
        _ = accounts["cloudflare-api"]


def test_token_is_redacted_in_repr() -> None:
    accounts = Accounts({"cloudflare-api": "s3cr3t"})

    assert "s3cr3t" not in repr(accounts["cloudflare-api"])
    assert "<redacted>" in repr(accounts["cloudflare-api"])
