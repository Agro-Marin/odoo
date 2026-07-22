"""DB-free unit tests for annotation-driven typed-route coercion.

Exercises :mod:`odoo.http._params` — pure stdlib+werkzeug, no registry — so the
coercion rules are pinned without an HTTP stack. Run in the tier-2 (real-import)
invocation, e.g. ``pytest odoo/http/tests``.
"""

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
    # PEP 604 ``X | None`` plus the legacy ``typing.Optional`` / ``typing.Union``
    # spellings must all reduce the same. The legacy forms are built via getattr
    # so this file itself stays PEP-604-clean under ruff.
    optional = getattr(typing, "Optional")  # noqa: B009
    union = getattr(typing, "Union")  # noqa: B009
    assert _resolve(int | None) == (int, None, True)
    assert _resolve(optional[int]) == (int, None, True)
    assert _resolve(union[int, None]) == (int, None, True)
    # A union of two real types is unsupported -> pass through.
    assert _resolve(int | str) == (None, None, False)


def test_resolve_list_forms():
    legacy_list = getattr(typing, "List")  # noqa: B009
    assert _resolve(list) == (list, None, False)
    assert _resolve(list[int]) == (list, int, False)
    assert _resolve(legacy_list[int]) == (list, int, False)
    # list[<non-primitive>] keeps the list target but drops the item type.
    assert _resolve(list[dict]) == (list, None, False)


def test_build_specs_skips_unannotated_and_unsupported():
    def ep(self, n: int, raw, note: bytes = b"", opt: int | None = None): ...

    specs = _spec(ep)
    # ``raw`` unannotated, ``note`` unsupported (bytes) -> both skipped.
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
    # integral float accepted (JS serializes 3 as 3.0).
    assert coerce_params({"n": 3.0}, _spec(ep)) == {"n": 3}


def test_float_rejects_non_finite():
    def ep(self, x: float): ...

    for bad in ("nan", "inf", "-inf"):
        with pytest.raises(BadRequest):
            coerce_params({"x": bad}, _spec(ep))


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
    """Regression: a str-typed param must reject a FileStorage/bytes/container.

    Before the whitelist fix these coerced to their Python ``repr`` (e.g.
    ``"<FileStorage: 'a.png' ...>"``), silently corrupting the value.
    """

    def ep(self, note: str): ...

    with pytest.raises(BadRequest):
        coerce_params({"note": value}, _spec(ep))


def test_str_param_stringifies_json_scalars():
    def ep(self, note: str): ...

    assert coerce_params({"note": 5}, _spec(ep)) == {"note": "5"}
    assert coerce_params({"note": True}, _spec(ep)) == {"note": "True"}
    assert coerce_params({"note": 2.5}, _spec(ep)) == {"note": "2.5"}


def test_required_missing_raises_optional_missing_skips():
    def ep(self, n: int, opt: int | None = None): ...

    specs = _spec(ep)
    # required ``n`` absent -> 400.
    with pytest.raises(BadRequest):
        coerce_params({}, specs)
    # optional ``opt`` absent -> skipped, ``n`` supplied so no error.
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
    # a scalar for a list param is wrapped into a single-element list.
    assert coerce_params({"ids": "7"}, specs) == {"ids": [7]}
