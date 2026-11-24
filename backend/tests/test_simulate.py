"""Unit tests for the X-Simulate-Failure header parser (no HTTP, no LLM)."""

import pytest

from app.simulate import InvalidSimulationHeader, parse_simulation_header

KEYS = ["key_1", "key_2"]


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, {}),
        ("", {}),
        ("key_1=429", {"key_1": 429}),
        (" key_1 = 429 , key_2=500 ", {"key_1": 429, "key_2": 500}),
        ("*=503", {"key_1": 503, "key_2": 503}),
        ("*=429,key_2=500", {"key_1": 429, "key_2": 500}),  # later entries win
    ],
)
def test_valid_headers(header, expected):
    assert parse_simulation_header(header, KEYS) == expected


@pytest.mark.parametrize("header", ["key_1", "key_1=", "key_1=abc", "key_1=418", "key_3=429"])
def test_invalid_headers(header):
    with pytest.raises(InvalidSimulationHeader):
        parse_simulation_header(header, KEYS)
