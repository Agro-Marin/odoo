"""Randomised differential: the three exports with no production reference.

`sort_ids_by_values` has `test_sort_parity_fuzz`, and the eight `_field_access`
functions have `test_field_access`, which runs the *same* assertions against the
accelerated and the pure-Python half. `csv_export`, `rows_to_dicts` and
`fast_clone` had neither — only hand-written expectations, which check the cases
somebody thought of.

The references are in `_native_references.py`; see it for why they live under
`tests/`. This file and `test_native_acceleration_pays` are the two halves of
the same argument and neither stands alone: agreement without a measurement is
free, and a measurement against a reference nobody checked is a ratio between
two different jobs.

The seed is fixed. A fuzz that picks a new corpus every run is one that fails on
somebody else's commit, and the value here is breadth of *shapes*, not novelty:
every generator below is a deliberate list of the things that break these
functions — the six formula prefixes, an embedded quote, comma and newline,
`False` against `0` against `""`, bytes, a lone surrogate, an int beyond i64.
"""

import copy
import random

import odoo_rust as fast
import pytest

from odoo.libs.tests._native_references import (
    FORMULA_PREFIXES,
    clone_ref,
    csv_export_ref,
    rows_to_dicts_ref,
)

SEED = 20260828

#: Spelled out, deliberately NOT derived from `FORMULA_PREFIXES`. A corpus
#: built from the constant under test shrinks exactly when that constant does,
#: so deleting a prefix from the reference would also delete the cell that
#: would have caught it. Measured: with these generated from the constant,
#: dropping `@`, tab and CR from the reference passed the whole suite; spelled
#: out, it fails. `test_the_corpus_covers_every_guarded_prefix` closes the
#: other direction — a prefix ADDED to the reference and not to this list.
_FORMULA_CELLS = ("=cmd", "-cmd", "+cmd", "@cmd", "\tcmd", "\rcmd")

#: Cells chosen for what they do to the writer, not for realism: identity
#: blanking (`False` vs `0` vs `""`), RFC 4180 escaping (quote, comma,
#: newline), every formula prefix, `bytes`, non-ASCII and an int too big for a
#: machine word.
CELLS = (
    None,
    False,
    True,
    0,
    1,
    -5,
    1.5,
    -0.0,
    "",
    "plain",
    'a"b',
    "a,b",
    "a\nb",
    "a\r\nb",
    "'already",
    "é",
    "😀",
    b"bytes",
    b"",
    "x" * 200,
    10**30,
    3.0,
    *_FORMULA_CELLS,
)

#: Values a cursor can hand back, plus two the ORM never produces but the
#: conversion must not corrupt.
SQL_VALUES = (None, True, 0, 1.5, "s", b"bytes", (1, 2), [1], {"k": 1}, 10**40)


def _capture(fn, *args):
    try:
        return ("ok", fn(*args))
    except Exception as exc:  # the exception TYPE is the result being compared
        return ("raise", type(exc).__name__)


def _json_like(rng, depth=0):
    if depth > 3 or rng.random() < 0.35:
        return rng.choice([None, True, False, 0, -1, 2.5, "", "s", "é", 10**30])
    roll = rng.random()
    if roll < 0.45:
        return {f"k{i}": _json_like(rng, depth + 1) for i in range(rng.randrange(0, 4))}
    if roll < 0.8:
        return [_json_like(rng, depth + 1) for _ in range(rng.randrange(0, 4))]
    return tuple(_json_like(rng, depth + 1) for _ in range(rng.randrange(0, 3)))


def test_the_corpus_covers_every_guarded_prefix():
    """The corpus must grow when the reference's guard list does.

    `_FORMULA_CELLS` is spelled out so that *removing* a prefix cannot hide
    itself; this is the other direction, where *adding* one would otherwise go
    untested because no cell in the corpus starts with it.
    """
    covered = {cell[0] for cell in _FORMULA_CELLS}
    assert covered == set(FORMULA_PREFIXES), (
        f"the corpus guards {sorted(covered)} but the reference guards "
        f"{sorted(FORMULA_PREFIXES)}; a prefix with no cell is untested"
    )


def test_csv_export_matches_the_reference():
    rng = random.Random(SEED)
    for _ in range(1500):
        ncols = rng.randrange(0, 6)
        headers = [f"h{i}" for i in range(ncols)]
        # Ragged on purpose: `csv.writer` emits as many fields as the row has,
        # and so must the accelerated version — it takes each row's own length,
        # not the header count.
        rows = [
            [rng.choice(CELLS) for _ in range(rng.randrange(0, ncols + 2))]
            for _ in range(rng.randrange(0, 5))
        ]
        accelerated = _capture(fast.csv_export, headers, [list(r) for r in rows])
        reference = _capture(csv_export_ref, headers, [list(r) for r in rows])
        assert accelerated == reference, f"headers={headers} rows={rows}"


def test_rows_to_dicts_matches_the_reference():
    rng = random.Random(SEED)
    for _ in range(1500):
        ncols = rng.randrange(0, 6)
        names = tuple(f"c{i}" for i in range(ncols))
        rows = [
            tuple(rng.choice(SQL_VALUES) for _ in range(ncols))
            for _ in range(rng.randrange(0, 5))
        ]
        assert _capture(fast.rows_to_dicts, names, rows) == _capture(
            rows_to_dicts_ref, names, rows
        ), f"names={names} rows={rows}"


def test_rows_to_dicts_refuses_a_row_of_the_wrong_width_like_the_reference():
    """`strict=True` on one side, an explicit length check on the other."""
    names = ("a", "b")
    for rows in ([(1,)], [(1, 2, 3)], [(1, 2), (1,)]):
        accelerated = _capture(fast.rows_to_dicts, names, rows)
        reference = _capture(rows_to_dicts_ref, names, rows)
        assert accelerated[0] == reference[0] == "raise", (
            f"{rows} was accepted by {'the accelerated path' if accelerated[0] == 'ok' else 'the reference'}"
        )


def test_fast_clone_matches_the_reference():
    rng = random.Random(SEED)
    for _ in range(2500):
        blob = _json_like(rng)
        assert _capture(fast.fast_clone, blob) == _capture(clone_ref, blob), (
            f"blob={blob!r}"
        )


def test_fast_clone_shares_no_container_with_its_original():
    """Equality is not the property that matters; independence is.

    A `fast_clone` that returned its argument would satisfy every assertion
    above. It did, for container subclasses, until `PyDict_CheckExact` became
    `PyDict_Check` — and a Properties field then handed the caller's live
    mapping to the field cache.
    """
    rng = random.Random(SEED)
    for _ in range(1500):
        blob = _json_like(rng)
        if not isinstance(blob, dict | list):
            continue
        clone = fast.fast_clone(blob)
        assert clone is not blob
        values = clone.values() if isinstance(clone, dict) else clone
        originals = blob.values() if isinstance(blob, dict) else blob
        for cloned, original in zip(values, originals, strict=True):
            if isinstance(original, dict | list):
                assert cloned is not original, f"shared substructure in {blob!r}"


@pytest.mark.parametrize(
    ("name", "reference"),
    [("csv_export", csv_export_ref), ("fast_clone", clone_ref)],
)
def test_the_reference_is_not_the_accelerated_function(name, reference):
    """Guards against the oracle quietly becoming the thing it checks.

    A reference that delegates would agree with the extension on every input
    ever generated, and this whole file would pass while measuring nothing.
    """
    assert reference is not getattr(fast, name)
    assert "odoo_rust" not in reference.__code__.co_names


def test_fast_clone_agrees_with_deepcopy_on_a_tree():
    """The two diverge only where JSON cannot go.

    `copy.deepcopy` memoizes, so it preserves aliasing between two slots that
    hold the same object; `fast_clone` duplicates. On a tree — which is every
    shape a Json or Properties value can take, both having round-tripped
    through `orjson` — they agree, and that is worth pinning because deepcopy is
    what production actually replaced.
    """
    rng = random.Random(SEED)
    for _ in range(300):
        blob = _json_like(rng)
        assert fast.fast_clone(blob) == copy.deepcopy(blob), f"blob={blob!r}"
