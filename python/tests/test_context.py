"""Tests for invocation-scoped Integrations addressing."""

import pytest
from shimpz.context import Integrations


def test_subscript_reaches_a_hyphenated_integration_id() -> None:
    value = "opaque-value"
    integrations = Integrations({"cloudflare-api": value})

    assert integrations["cloudflare-api"].access_token == value


def test_attribute_access_reaches_an_identifier_safe_id() -> None:
    value = "opaque-value"
    integrations = Integrations({"cloudflare": value})

    assert integrations.cloudflare.access_token == value


def test_missing_subscript_id_raises_key_error() -> None:
    integrations = Integrations({"cloudflare": "token"})

    with pytest.raises(KeyError, match="was not injected"):
        _ = integrations["cloudflare-api"]


def test_token_is_redacted_in_repr() -> None:
    integrations = Integrations({"cloudflare-api": "s3cr3t"})

    assert "s3cr3t" not in repr(integrations["cloudflare-api"])
    assert "<redacted>" in repr(integrations["cloudflare-api"])
