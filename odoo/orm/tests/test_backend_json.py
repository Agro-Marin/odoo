import math

import pytest
from psycopg.errors import (
    InvalidTextRepresentation,
    NumericValueOutOfRange,
    UntranslatableCharacter,
)
from psycopg.types.json import Json, Jsonb

from odoo.orm.runtime.backend import _unwrap_json


@pytest.mark.parametrize("wrapper", [Json, Jsonb])
def test_json_storage_normalizes_and_detaches_values(wrapper):
    items = [2]
    source = {1: {"items": items, "pair": (3, 4), "large": 10**30 + 1}}
    stored = _unwrap_json(wrapper(source))
    items.append(5)
    assert stored == {"1": {"items": [2], "pair": [3, 4], "large": 10**30 + 1}}


@pytest.mark.parametrize("wrapper", [Json, Jsonb])
def test_json_storage_honors_the_wrapper_encoder(wrapper):
    assert _unwrap_json(wrapper(object(), dumps=lambda value: '{"encoded":true}')) == {
        "encoded": True
    }


@pytest.mark.parametrize("wrapper", [Json, Jsonb])
def test_jsonb_normalizes_exponents_and_signed_zero(wrapper):
    stored = _unwrap_json(wrapper({"integer": 1e20, "zero": -0.0, "fraction": 1e-7}))
    assert type(stored["integer"]) is int
    assert stored["integer"] == 100000000000000000000
    assert type(stored["zero"]) is float
    assert math.copysign(1, stored["zero"]) == 1
    assert stored["fraction"] == 1e-7


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), "\ud800"])
def test_jsonb_rejects_invalid_json_values(value):
    with pytest.raises(InvalidTextRepresentation):
        _unwrap_json(Json({"nested": [value]}))


@pytest.mark.parametrize("value", [{"value": "\0"}, {"\0": "value"}])
def test_jsonb_rejects_nul_in_keys_and_values(value):
    with pytest.raises(UntranslatableCharacter):
        _unwrap_json(Json(value))


@pytest.mark.parametrize("number", ["1e131072", "1e-16384"])
def test_jsonb_rejects_numbers_outside_the_numeric_range(number):
    with pytest.raises(NumericValueOutOfRange):
        _unwrap_json(Json(None, dumps=lambda value: number))


def test_jsonb_accepts_zero_with_a_large_positive_exponent():
    assert _unwrap_json(Json(None, dumps=lambda value: "0e131072")) == 0
