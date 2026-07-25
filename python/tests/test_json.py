"""Tests for strict public JSON decoding."""

import pytest
from shimpz import strict_loads


def test_rejects_duplicate_object_keys() -> None:
    with pytest.raises(ValueError):
        strict_loads('{"a":1,"a":2}')


def test_rejects_non_finite_constants() -> None:
    with pytest.raises(ValueError):
        strict_loads("NaN")


def test_parses_valid_json() -> None:
    assert strict_loads('{"a":1,"b":2}') == {"a": 1, "b": 2}
