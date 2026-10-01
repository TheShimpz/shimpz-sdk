"""Tests for immutable catalog copy values."""

import dataclasses

import pytest
from shimpz import Param, Text, dns_name, domain, identifier, integer, text


def test_text_keeps_the_literal_template_and_sorted_kind_wrapped_params() -> None:
    copy = text("DNS changes to publish: {count}. Zone: {zone}.", zone=domain("example.com"), count=integer(3, digits=4))

    assert copy == Text(
        "DNS changes to publish: {count}. Zone: {zone}.",
        (("count", Param("integer", 3, 4)), ("zone", Param("domain", "example.com", 253))),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        copy.template = "Other"  # type: ignore[misc]


def test_text_records_an_explicit_field_bound() -> None:
    assert text("Zone", max_length=80).max_length == 80
    assert identifier("rec-1", max_length=32) == Param("identifier", "rec-1", 32)
    assert dns_name("_dmarc.example.com") == Param("dns_name", "_dmarc.example.com", 253)
    assert dns_name("_dmarc", max_length=20) == Param("dns_name", "_dmarc", 20)

    with pytest.raises(ValueError, match="max_length"):
        text("Zone", max_length=100)


@pytest.mark.parametrize(
    "build",
    [
        lambda: text(b"Zone"),
        lambda: text("Zone {zone}", zone="example.com"),
        lambda: integer("3", digits=1),
        lambda: integer(True, digits=1),
        lambda: domain(None),
        lambda: dns_name(b"_dmarc"),
        lambda: identifier(7, max_length=8),
    ],
)
def test_refuses_plain_values_where_kinds_are_required(build) -> None:
    with pytest.raises(TypeError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: integer(1, digits=0),
        lambda: integer(1, digits=16),
        lambda: domain("example.com", max_length=254),
        lambda: dns_name("_dmarc", max_length=254),
        lambda: dns_name("_dmarc", max_length=0),
        lambda: identifier("rec", max_length=129),
        lambda: identifier("rec", max_length=True),
    ],
)
def test_refuses_parameter_maxima_outside_their_kind(build) -> None:
    with pytest.raises(ValueError, match="maximum"):
        build()
