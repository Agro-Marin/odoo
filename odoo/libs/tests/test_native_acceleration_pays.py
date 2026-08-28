"""Every function `odoo_rust` exports must beat the Python it replaces.

`odoo_rust` is a **hard dependency** — `odoo/init.py` refuses to start without
it — and everything it buys is speed. Nothing measured whether it delivers any,
and that is how `sort_ids_by_values` spent its whole existence **13-16% SLOWER**
than `_fallback.sort_ids_by_values` on a column of short distinct strings: the
shape an ORM produces every time it sorts a recordset by a `Char` field. Every
suite was green throughout, because a slower correct answer is still correct.

The judgement this restores has been made by hand before and then never
repeated: `scalar_cache_get` lives in `_fallback.py` and is deliberately NOT
accelerated, because three `dict[key]` subscripts are already three C-level
lookups and the PyO3 boundary costs more than the work.

## Where each reference comes from

Four of the twelve exports have a reference in **production** code, because
something still calls it: the eight `_field_access` functions have
`_fallback.py`, which the test suite holds to the same assertions, and
`origin_ids` has `_origin_ids_python`, which `orm/helpers._origin_ids` uses for
any non-tuple input.

The other three are defined **here**, and deliberately not in production. An
unused twin sitting beside the real function is not a reference, it is drift
waiting to happen — the crate carried eight such `_safe` functions "for
documentation and semantic comparison", nothing called them so nothing compared
them, and one had quietly acquired different subclass semantics from the
function it documented. A benchmark reference belongs in the benchmark.

## Why a wall-clock assertion is not flaky here

It asserts a **ratio of two measurements taken in the same process, moments
apart**, never an absolute time. A loaded machine slows both sides, so the ratio
holds; `min()` over repeats takes each side's best run, which is the least noisy
statistic available — interference can only ever make a run slower.

## The data is the test

A benchmark on convenient data measures nothing. The first version of this file
used a 37-value column for the sort cases and **passed against the very build
whose regression it exists to catch**, because at that width the accelerated
sort ran at 0.52. It was caught the way every regression test here is checked:
by building the parent commit and running the new file against it.
"""

import copy
import csv
import io
import timeit
from types import SimpleNamespace

import odoo_rust as fast
import pytest

from odoo.libs._field_access._fallback import (
    batch_cache_fill,
    batch_cache_filter,
    batch_cache_get,
    batch_cache_values,
    batch_group_ids,
    sort_ids_by_cache,
    sort_ids_by_values,
    to_prefetch_ids,
)
from odoo.orm.helpers import _origin_ids_python

#: The accelerated call must take at most this fraction of the reference's time.
#:
#: Placed between the two numbers that matter rather than picked round. The
#: worst legitimate ratio is `sort_ids_by_values` at **0.81** — deliberately so:
#: its column below is the least favourable shape there is, not a typical one.
#: The regression this suite exists to catch measured **1.10-1.16**. 0.95 sits
#: 1.17x above the first and 1.16x below the second, the widest margin available
#: on both sides at once.
#:
#: Not 1.0: a function that has drawn level has stopped paying for the boundary
#: it crosses, the wheel it lives in and the `unsafe` it is written in, and is
#: worth reconsidering before it goes backwards.
MAX_RATIO = 0.95


# ── References with no production twin ───────────────────────────────────────


def csv_export_py(headers, rows):
    """`CSVExport.from_data` as it stood before `web.rs` replaced it.

    The accelerated version additionally guards `@`, tab and CR — the remaining
    OWASP formula-injection prefixes — so it does strictly more work than this,
    which can only understate its lead.
    """
    fp = io.StringIO()
    writer = csv.writer(fp, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    for row in rows:
        cells = []
        for value in row:
            if value is None or value is False:
                value = ""
            elif isinstance(value, bytes):
                value = value.decode()
            if isinstance(value, str) and value.startswith(("=", "-", "+")):
                value = "'" + value
            cells.append(value)
        writer.writerow(cells)
    return fp.getvalue().encode()


def rows_to_dicts_py(names, rows):
    """The pattern `rows.rs` names as the one it replaced."""
    return [dict(zip(names, row, strict=True)) for row in rows]


def fast_clone_py(obj):
    """`clone.rs`'s semantics in Python: containers rebuilt, leaves shared.

    `isinstance`, not `type(x) is`, to match `PyDict_Check` — the accelerated
    version rebuilds subclasses too, and normalizes them to the builtin type.

    NOT what production replaced: `Json.convert_to_record` called
    `copy.deepcopy`, which is slower again because it memoizes. Both ratios are
    reported by `test_fast_clone_also_beats_the_deepcopy_it_replaced`.
    """
    if isinstance(obj, dict):
        return {key: fast_clone_py(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [fast_clone_py(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(fast_clone_py(value) for value in obj)
    return obj


class _NewId:
    """Falsy, with an `origin` — what `origin_ids` exists to unwrap."""

    __slots__ = ("origin",)

    def __init__(self, origin):
        self.origin = origin

    def __bool__(self):
        return False


#: Every reference, keyed by the name it stands in for.
slow = SimpleNamespace(
    batch_cache_fill=batch_cache_fill,
    batch_cache_filter=batch_cache_filter,
    batch_cache_get=batch_cache_get,
    batch_cache_values=batch_cache_values,
    batch_group_ids=batch_group_ids,
    sort_ids_by_cache=sort_ids_by_cache,
    sort_ids_by_values=sort_ids_by_values,
    to_prefetch_ids=to_prefetch_ids,
    origin_ids=_origin_ids_python,
    csv_export=csv_export_py,
    rows_to_dicts=rows_to_dicts_py,
    fast_clone=fast_clone_py,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

#: Enough records that the per-call boundary cost is not the whole measurement,
#: few enough that the suite stays a Tier-1 suite.
N = 500

#: The sort cases run wider: the regression did not appear at all below n≈1000.
SORT_N = 1000

_PENDING = object()
_NONE_VAL = object()

_IDS = tuple(range(1, N + 1))
_CACHE = {i: f"v{i % 37}" for i in _IDS}
_GROUPS = [f"g{i % 7}" for i in _IDS]

#: Distinct, short, and in no useful order — the shape a `Char` column takes
#: when a recordset is sorted by a reference or a name. Short matters: CPython's
#: string comparison gets cheaper as the strings do while Rust's fixed
#: per-comparison cost does not, so short distinct strings are where the
#: accelerated path is *least* ahead. On the build that carried the regression
#: this column measured 1.16 and a 37-value one measured 0.52.
_SORT_IDS = tuple(range(1, SORT_N + 1))
_SORT_COLUMN = [f"v{(i * 7) % SORT_N}" for i in _SORT_IDS]
_SORT_CACHE = dict(zip(_SORT_IDS, _SORT_COLUMN, strict=True))

_COLUMNS = tuple(f"c{i}" for i in range(12))
_SQL_ROWS = [tuple(range(12)) for _ in range(N)]
_CSV_HEADERS = [f"h{i}" for i in range(12)]
_CSV_ROWS = [[f"cell {i}-{j}" for j in range(12)] for i in range(N)]
_BLOB = {"a": list(range(20)), "b": {"c": [{"d": i} for i in range(20)]}, "e": "x" * 50}
_ORIGIN_IDS = tuple(i if i % 3 else _NewId(i * 10) for i in range(1, N + 1))


def _results():
    return [{"id": i} for i in _IDS]


#: `(name, call)` where `call` takes the module to exercise, so the accelerated
#: and reference halves cannot drift apart into two different benchmarks.
CASES = (
    ("batch_cache_get", lambda m: m.batch_cache_get(_CACHE, _IDS, _PENDING, _NONE_VAL)),
    ("batch_cache_filter", lambda m: m.batch_cache_filter(_CACHE, _IDS, _PENDING)),
    ("batch_cache_values", lambda m: m.batch_cache_values(_CACHE, _IDS, _PENDING)),
    (
        "batch_cache_fill",
        lambda m: m.batch_cache_fill(
            _CACHE, _IDS, _results(), "f", _PENDING, _NONE_VAL
        ),
    ),
    ("batch_group_ids", lambda m: m.batch_group_ids(_IDS, _GROUPS)),
    (
        "sort_ids_by_values",
        lambda m: m.sort_ids_by_values(_SORT_IDS, _SORT_COLUMN, False, None),
    ),
    (
        "sort_ids_by_cache",
        lambda m: m.sort_ids_by_cache(_SORT_CACHE, _SORT_IDS, _PENDING, False, None),
    ),
    ("to_prefetch_ids", lambda m: m.to_prefetch_ids(1, _IDS, {}, 1000)),
    ("origin_ids", lambda m: m.origin_ids(_ORIGIN_IDS)),
    ("rows_to_dicts", lambda m: m.rows_to_dicts(_COLUMNS, _SQL_ROWS)),
    ("csv_export", lambda m: m.csv_export(_CSV_HEADERS, [list(r) for r in _CSV_ROWS])),
    ("fast_clone", lambda m: m.fast_clone(_BLOB)),
)


def _best(call, module) -> float:
    """Fastest observed seconds-per-call. See the module docstring on `min`."""
    number, repeat = 50, 7
    return (
        min(timeit.repeat(lambda: call(module), number=number, repeat=repeat)) / number
    )


@pytest.mark.parametrize(("name", "call"), CASES, ids=[c[0] for c in CASES])
def test_the_accelerated_call_beats_the_reference(name, call):
    accelerated = _best(call, fast)
    reference = _best(call, slow)
    ratio = accelerated / reference
    assert ratio <= MAX_RATIO, (
        f"{name} takes {ratio:.2f}x the pure-Python reference's time "
        f"({accelerated * 1e6:.2f}us against {reference * 1e6:.2f}us); the bar "
        f"is {MAX_RATIO}. It is a hard dependency whose only purpose is to be "
        f"faster. Either the Rust has a defect — `sort_ids_by_values` reached "
        f"1.16x by dispatching on a column type it had already decided — or the "
        f"boundary costs more than the work, in which case drop the export and "
        f"keep the reference, as `scalar_cache_get` did."
    )


@pytest.mark.parametrize(("name", "call"), CASES, ids=[c[0] for c in CASES])
def test_both_sides_compute_the_same_thing(name, call):
    """A ratio between two different jobs is not a measurement.

    Three of the references here exist only in this file, so nothing else can
    notice if one quietly does less work than the function it stands in for — a
    `csv_export_py` that skipped the formula guard, say, would hand the
    accelerated half a lead it had not earned. The eight `_field_access`
    references are held to `_fallback`'s own correctness suite; these are held
    here, on the exact fixtures being timed.

    Equality on the benchmark data, not in general: `csv_export` deliberately
    guards `@`, tab and CR where the Python original guarded only `=`, `-` and
    `+`, so the two agree on this data and are meant to disagree on a cell
    starting with one of the three it added.
    """
    assert call(fast) == call(slow)


def test_fast_clone_also_beats_the_deepcopy_it_replaced():
    """`fast_clone_py` is the fair comparison; `copy.deepcopy` is the real one.

    Production called `copy.deepcopy`, which is slower again because it keeps a
    memo — correct for a general object graph and unnecessary for the JSON-shaped
    trees this is used on.
    """
    accelerated = _best(lambda m: m.fast_clone(_BLOB), fast)
    deepcopy_time = (
        min(timeit.repeat(lambda: copy.deepcopy(_BLOB), number=50, repeat=7)) / 50
    )
    assert accelerated < deepcopy_time / 2, (
        f"fast_clone is {accelerated * 1e6:.2f}us against copy.deepcopy's "
        f"{deepcopy_time * 1e6:.2f}us; it replaced deepcopy on the strength of a "
        f"large margin and no longer has one"
    )


def test_every_accelerated_function_is_measured():
    """No export may be unmeasured.

    Read from the crate's own `__all__`, so a function added to the extension
    arrives with its measurement or fails here. This used to skip anything
    without a `_fallback` twin, which quietly excused four of the twelve —
    `csv_export`, `fast_clone`, `origin_ids` and `rows_to_dicts` — the four that
    had never been compared against anything at all.
    """
    measured = {name for name, _ in CASES}
    exported = {name for name in fast.__all__ if callable(getattr(fast, name, None))}
    assert exported == measured, (
        f"accelerated functions with no measurement: {sorted(exported - measured)}; "
        f"measured but no longer exported: {sorted(measured - exported)}"
    )
    assert measured <= set(vars(slow)), (
        f"no reference for {sorted(measured - set(vars(slow)))}"
    )


def test_the_field_access_references_are_the_production_ones():
    """The eight `_field_access` references must be `_fallback.py`'s.

    Not copies of it: `_fallback` is exercised by `test_field_access`, which
    runs the SAME assertions against it and the accelerated half. A reference
    that only this file uses is one nothing checks for correctness, and then the
    ratio compares against something that may not compute the right answer.
    """
    for name in (
        "batch_cache_fill",
        "batch_cache_filter",
        "batch_cache_get",
        "batch_cache_values",
        "batch_group_ids",
        "sort_ids_by_cache",
        "sort_ids_by_values",
        "to_prefetch_ids",
    ):
        reference = getattr(slow, name)
        assert reference.__module__.endswith("_fallback"), (
            f"{name}'s reference is {reference.__module__}, not _fallback — a "
            f"benchmark-only copy is not held to _fallback's correctness tests"
        )
