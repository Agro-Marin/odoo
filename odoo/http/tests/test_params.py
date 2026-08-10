import typing

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest

from odoo.http._params import (
    ParamSpec,
    _resolve,
    build_param_specs,
    coerce_params,
)


def _spec(fn):
    return build_param_specs(fn)


def test_resolve_optional_forms_are_equivalent():
    optional = typing.Optional  # noqa: TID251  legacy spelling under test
    union = typing.Union  # noqa: TID251  legacy spelling under test
    assert _resolve(int | None) == (int, None, True)
    assert _resolve(optional[int]) == (int, None, True)
    assert _resolve(union[int, None]) == (int, None, True)
    assert _resolve(int | str) == (None, None, False)


def test_resolve_list_forms():
    legacy_list = list
    assert _resolve(list) == (list, None, False)
    assert _resolve(list[int]) == (list, int, False)
    assert _resolve(legacy_list[int]) == (list, int, False)
    assert _resolve(list[dict]) == (list, None, False)


def test_build_specs_skips_unannotated_and_unsupported():
    def ep(self, n: int, raw, note: bytes = b"", opt: int | None = None): ...

    specs = _spec(ep)
    assert set(specs) == {"n", "opt"}
    assert specs["n"] == ParamSpec(int, None, False, True)
    assert specs["opt"] == ParamSpec(int, None, True, False)


def test_scalar_coercions():
    def ep(self, n: int, x: float, flag: bool, name: str): ...

    out = coerce_params({"n": "5", "x": "2.5", "flag": "on", "name": 7}, _spec(ep))
    assert out == {"n": 5, "x": 2.5, "flag": True, "name": "7"}


@pytest.mark.parametrize("bad", ["abc", "3.7", "0x10", "", "1e999"])
def test_int_rejects_non_integers(bad):
    def ep(self, n: int): ...

    with pytest.raises(BadRequest):
        coerce_params({"n": bad}, _spec(ep))


def test_int_rejects_bool_and_fractional_float():
    def ep(self, n: int): ...

    for bad in (True, 3.7):
        with pytest.raises(BadRequest):
            coerce_params({"n": bad}, _spec(ep))
    assert coerce_params({"n": 3.0}, _spec(ep)) == {"n": 3}


def test_float_rejects_non_finite():
    def ep(self, x: float): ...

    for bad in ("nan", "inf", "-inf"):
        with pytest.raises(BadRequest):
            coerce_params({"x": bad}, _spec(ep))


@pytest.mark.parametrize("bad", ["1_000", "١٢", "٥", "1 "])
def test_int_rejects_python_only_number_spellings(bad):

    def ep(self, n: int): ...

    with pytest.raises(BadRequest):
        coerce_params({"n": bad}, _spec(ep))


@pytest.mark.parametrize("bad", ["1_000.5", "٥.٥", "1_0e3"])
def test_float_rejects_python_only_number_spellings(bad):
    def ep(self, x: float): ...

    with pytest.raises(BadRequest):
        coerce_params({"x": bad}, _spec(ep))


def test_number_coercion_still_tolerates_surrounding_whitespace():

    def ep(self, n: int, x: float): ...

    assert coerce_params({"n": "  42 ", "x": " 3.14 "}, _spec(ep)) == {
        "n": 42,
        "x": 3.14,
    }


@pytest.mark.parametrize(
    "value",
    [
        FileStorage(filename="a.png"),
        b"raw-bytes",
        {"a": 1},
        [1, 2],
    ],
)
def test_str_param_rejects_non_scalars(value):

    def ep(self, note: str): ...

    with pytest.raises(BadRequest):
        coerce_params({"note": value}, _spec(ep))


def test_str_param_stringifies_json_numbers():
    def ep(self, note: str): ...

    assert coerce_params({"note": 5}, _spec(ep)) == {"note": "5"}
    assert coerce_params({"note": 2.5}, _spec(ep)) == {"note": "2.5"}


def test_str_param_rejects_bool():

    def ep(self, note: str): ...

    with pytest.raises(BadRequest):
        coerce_params({"note": True}, _spec(ep))


def test_string_annotations_are_resolved():

    def ep(self, n: "int", opt: "int | None" = None): ...  # noqa: UP037

    specs = _spec(ep)
    assert specs["n"] == ParamSpec(int, None, False, True)
    assert specs["opt"] == ParamSpec(int, None, True, False)
    assert coerce_params({"n": "5"}, specs) == {"n": 5}


def test_unresolvable_string_annotation_passes_through():

    def ep(self, n: "int", ghost: "NotARealName" = None): ...  # noqa: UP037, F821

    specs = _spec(ep)
    assert set(specs) == {"n"}
    assert specs["n"] == ParamSpec(int, None, False, True)


def test_required_missing_raises_optional_missing_skips():
    def ep(self, n: int, opt: int | None = None): ...

    specs = _spec(ep)
    with pytest.raises(BadRequest):
        coerce_params({}, specs)
    assert coerce_params({"n": 1}, specs) == {"n": 1}


def test_null_only_allowed_when_optional():
    def ep(self, n: int, opt: int | None = None): ...

    with pytest.raises(BadRequest):
        coerce_params({"n": None}, _spec(ep))
    assert coerce_params({"n": 1, "opt": None}, _spec(ep)) == {"n": 1, "opt": None}


def test_list_of_ints_and_untyped_list():
    def ep(self, ids: list[int] | None = None, raw: list | None = None): ...

    specs = _spec(ep)
    assert coerce_params({"ids": ["1", "2"], "raw": ["a", 3]}, specs) == {
        "ids": [1, 2],
        "raw": ["a", 3],
    }
    assert coerce_params({"ids": "7"}, specs) == {"ids": [7]}
