"""Each accelerated function must actually beat the Python it replaces.

`odoo_rust` is a **hard dependency** — `odoo/init.py` refuses to start without
it — and the only thing it buys is speed. Nothing checked that it delivers any,
and that is not hypothetical: `sort_ids_by_values` was **13-16% SLOWER** than
`_fallback.sort_ids_by_values` on a column of short distinct strings, which is
what an ORM produces every time it sorts a recordset by a `Char` field. It had
been for as long as the function existed. Every suite was green throughout,
because a slower correct answer is still a correct answer.

The crate has removed a function for exactly this before: `scalar_cache_get` is
implemented in `_fallback.py` and deliberately *not* exported, because three
`dict[key]` subscripts are already three C-level lookups and the PyO3 call
boundary costs more than the work. That judgement was made once, by hand, and
then never re-checked for anything else.

## Why a wall-clock assertion is not flaky here

It asserts a **ratio of two measurements taken in the same process, moments
apart**, never an absolute time. A loaded machine slows both sides, so the ratio
holds; `min()` over repeats takes each side's best run, which is what makes a
timing robust — interference can only ever make a run slower, so the minimum is
the least noisy statistic available.

Measured ratios are 0.16 to 0.81 against a bar of :data:`MAX_RATIO`, and the
regression this exists to catch measured 1.10-1.16 — see that constant for how
the bar was placed between them.

## The data is the test

A benchmark on convenient data measures nothing. The first version of this file
used the same 37-value column as the cache cases and **passed against the very
build whose regression it was written for**: at that width and with that many
duplicates the accelerated sort ran at 0.52. The shape that discriminates is
distinct, short and unordered — see :data:`_SORT_COLUMN`.
"""

import ast
import timeit
from pathlib import Path
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

#: The reference half, shaped like a module so one `call` can be handed either
#: implementation. Bound by name rather than as `from odoo.libs._field_access
#: import _fallback`: that form reaches a leaf module through its area package,
#: which `test_area_submodule_surface` pins precisely because
#: `libs_facade_check` cannot see it. The names are what this suite needs, so
#: the names are what it imports.
slow = SimpleNamespace(
    batch_cache_fill=batch_cache_fill,
    batch_cache_filter=batch_cache_filter,
    batch_cache_get=batch_cache_get,
    batch_cache_values=batch_cache_values,
    batch_group_ids=batch_group_ids,
    sort_ids_by_cache=sort_ids_by_cache,
    sort_ids_by_values=sort_ids_by_values,
    to_prefetch_ids=to_prefetch_ids,
)

#: The accelerated call must take at most this fraction of the reference's time.
#:
#: Placed between the two numbers that matter rather than picked round. The
#: worst legitimate ratio is `sort_ids_by_values` at **0.81** — deliberately so:
#: its column below is the least favourable shape there is, not a typical one.
#: The regression this suite exists to catch measured **1.10-1.16**. 0.95 sits
#: 1.17x above the first and 1.16x below the second, which is the widest margin
#: available on both sides at once.
#:
#: Not 1.0: a function that has drawn level has stopped paying for the boundary
#: it crosses, the wheel it lives in and the `unsafe` it is written in, and is
#: worth reconsidering before it goes backwards.
MAX_RATIO = 0.95

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


def _reference_functions() -> set[str]:
    """Public function names in `_fallback.py`, read from source.

    Not from the `slow` namespace above: that lists the eight this suite knows
    about, so asking it whether a NINTH exists would always answer no — the
    check would confirm its own premise and never fire.
    """
    module = Path(__file__).resolve().parents[1] / "_fallback.py"
    return {
        node.name
        for node in ast.parse(module.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }


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


def test_every_accelerated_function_with_a_reference_is_measured():
    """A new accelerated function must arrive with its measurement.

    The check is worth nothing if a function can be added to the crate and to
    `_fallback.py` without anyone asking whether it earns its place.

    Read from the crate's own `__all__`, not the `_field_access` facade: the
    question is what the *extension* exports, and the facade deliberately
    re-exports one pure-Python function alongside them. A name with no
    `_fallback` twin — `csv_export`, `fast_clone`, `origin_ids`,
    `rows_to_dicts` — has nothing to be compared against and is skipped; that
    is a gap in `_fallback.py`, not in this list.
    """
    measured = {name for name, _ in CASES}
    comparable = {
        name
        for name in fast.__all__
        # `scalar_cache_get` is the counter-example this suite exists to
        # remember: it has a reference but no accelerated version, because
        # measuring said the boundary cost more than three dict subscripts.
        if callable(getattr(fast, name, None)) and name in _reference_functions()
    }
    assert comparable == measured, (
        f"accelerated functions with a pure-Python reference but no measurement: "
        f"{sorted(comparable - measured)}; measured but no longer accelerated: "
        f"{sorted(measured - comparable)}"
    )
