import copy
import random

import pytest

from odoo.libs.tests._native_references import (
    FORMULA_PREFIXES,
    clone_ref,
    csv_export_ref,
    rows_to_dicts_ref,
)

fast = pytest.importorskip(
    "odoo_rust", exc_type=ImportError
)  # a parity test needs both sides

SEED = 20260828

_FORMULA_CELLS = ("=cmd", "-cmd", "+cmd", "@cmd", "\tcmd", "\rcmd")

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

SQL_VALUES = (None, True, 0, 1.5, "s", b"bytes", (1, 2), [1], {"k": 1}, 10**40)


def _capture(fn, *args):
    try:
        return ("ok", fn(*args))
    except Exception as exc:
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
    assert reference is not getattr(fast, name)
    assert "odoo_rust" not in reference.__code__.co_names


def test_fast_clone_agrees_with_deepcopy_on_a_tree():
    rng = random.Random(SEED)
    for _ in range(300):
        blob = _json_like(rng)
        assert fast.fast_clone(blob) == copy.deepcopy(blob), f"blob={blob!r}"


def test_rows_to_dicts_refuses_rows_that_shrink_under_a_reentrant_name():
    rows = [(1, 2)] * 50

    class Key(str):
        __slots__ = ()

        def __hash__(self):
            rows.clear()
            return 7

    with pytest.raises(ValueError):
        fast.rows_to_dicts((Key("a"), "b"), rows)


@pytest.mark.parametrize("clone", [fast.fast_clone, clone_ref], ids=["native", "ref"])
def test_fast_clone_refuses_a_dict_that_changes_size_while_cloned(clone):
    source: dict = {}

    class Key:
        armed = False

        def __hash__(self):
            if self.armed:
                source.clear()
                source.update({f"k{i}": [i] for i in range(64)})
            return 1

    key = Key()
    source.update({key: [1], "b": [2], "c": [3]})
    key.armed = True
    with pytest.raises(RuntimeError):
        clone(source)
