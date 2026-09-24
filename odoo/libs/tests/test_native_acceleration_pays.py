import copy
import time
from types import SimpleNamespace

import pytest

from odoo.libs._field_access._fallback import (
    batch_cache_fill,
    batch_cache_filter,
    batch_cache_get,
    batch_group_ids,
    sort_ids_by_cache,
    to_prefetch_ids,
)
from odoo.libs._trigger_trees import get_trigger_trees
from odoo.libs.accel import origin_ids_python as _origin_ids_python
from odoo.libs.tests._native_references import (
    NewId,
    clone_ref,
    csv_export_ref,
    rows_to_dicts_ref,
)

fast = pytest.importorskip("odoo_rust", exc_type=ImportError)

MAX_RATIO = 0.82

slow = SimpleNamespace(
    batch_cache_fill=batch_cache_fill,
    batch_cache_filter=batch_cache_filter,
    batch_cache_get=batch_cache_get,
    batch_group_ids=batch_group_ids,
    get_trigger_trees=get_trigger_trees,
    sort_ids_by_cache=sort_ids_by_cache,
    to_prefetch_ids=to_prefetch_ids,
    origin_ids=_origin_ids_python,
    csv_export=csv_export_ref,
    rows_to_dicts=rows_to_dicts_ref,
    fast_clone=clone_ref,
)

N = 500

SORT_N = 1000

_PENDING = object()
_NONE_VAL = object()

_IDS = tuple(range(1, N + 1))
_CACHE = {i: f"v{i % 37}" for i in _IDS}
_GROUPS = [f"g{i % 7}" for i in _IDS]

_SORT_IDS = tuple(range(1, SORT_N + 1))
_SORT_COLUMN = [f"v{(i * 7) % SORT_N}" for i in _SORT_IDS]
_SORT_CACHE = dict(zip(_SORT_IDS, _SORT_COLUMN, strict=True))

_COLUMNS = tuple(f"c{i}" for i in range(12))
_SQL_ROWS = [tuple(range(12)) for _ in range(N)]
_CSV_HEADERS = [f"h{i}" for i in range(12)]
_CSV_ROWS = [[f"cell {i}-{j}" for j in range(12)] for i in range(N)]
_BLOB = {"a": list(range(20)), "b": {"c": [{"d": i} for i in range(20)]}, "e": "x" * 50}
_ORIGIN_IDS = tuple(i if i % 3 else NewId(i * 10) for i in range(1, N + 1))


def _diamond_graph(depth: int):
    triggers: list = []
    meta: list = []

    def field(m2o=False, o2m=False, name=0, inverse=0, model=0, comodel=0):
        meta.append((m2o, o2m, name, inverse, model, comodel, len(meta)))
        return len(meta) - 1

    top = [field() for _ in range(depth + 1)]
    for i in range(depth):
        a, b, label = field(), field(), field()
        triggers.append((top[i], [([], [a, b])]))
        triggers.append((a, [([label], [top[i + 1]])]))
        triggers.append((b, [([label], [top[i + 1]])]))
    return triggers, meta


_TRIGGERS, _TRIGGER_META = _diamond_graph(40)


def _results():
    return [{"id": i} for i in _IDS]


def _shared(*args):
    return lambda: args


# a case is (name, prepare, call): prepare builds the call's arguments, outside
# the timing, fresh for every call since some implementations mutate them
CASES = (
    (
        "batch_cache_get",
        _shared(_CACHE, _IDS, _PENDING, _NONE_VAL),
        lambda m, args: m.batch_cache_get(*args),
    ),
    (
        "batch_cache_filter",
        _shared(_CACHE, _IDS, _PENDING),
        lambda m, args: m.batch_cache_filter(*args),
    ),
    (
        "batch_cache_fill",
        lambda: (_CACHE, _IDS, _results(), "f", _PENDING, _NONE_VAL),
        lambda m, args: m.batch_cache_fill(*args),
    ),
    (
        "batch_group_ids",
        _shared(_IDS, _GROUPS),
        lambda m, args: m.batch_group_ids(*args),
    ),
    (
        "sort_ids_by_cache",
        _shared(_SORT_CACHE, _SORT_IDS, _PENDING, False, True),
        lambda m, args: m.sort_ids_by_cache(*args),
    ),
    (
        "to_prefetch_ids",
        lambda: (1, _IDS, {}, 1000),
        lambda m, args: m.to_prefetch_ids(*args),
    ),
    ("origin_ids", _shared(_ORIGIN_IDS), lambda m, args: m.origin_ids(*args)),
    (
        "get_trigger_trees",
        _shared(_TRIGGERS, _TRIGGER_META),
        lambda m, args: m.get_trigger_trees(*args),
    ),
    (
        "rows_to_dicts",
        _shared(_COLUMNS, _SQL_ROWS),
        lambda m, args: m.rows_to_dicts(*args),
    ),
    (
        "csv_export",
        lambda: (_CSV_HEADERS, [list(row) for row in _CSV_ROWS]),
        lambda m, args: m.csv_export(*args),
    ),
    ("fast_clone", _shared(_BLOB), lambda m, args: m.fast_clone(*args)),
)

_NUMBER, _ROUNDS = 50, 7


def _batch(module, prepare, call) -> float:
    batch = [prepare() for _ in range(_NUMBER)]
    start = time.perf_counter()
    for args in batch:
        call(module, args)
    return (time.perf_counter() - start) / _NUMBER


def _best_of(*sides) -> list[float]:
    # the sides take turns, so a machine slowing down weighs on each alike
    best = [float("inf")] * len(sides)
    for _round in range(_ROUNDS):
        for position, side in enumerate(sides):
            best[position] = min(best[position], _batch(*side))
    return best


@pytest.mark.parametrize(
    ("name", "prepare", "call"), CASES, ids=[case[0] for case in CASES]
)
def test_the_accelerated_call_beats_the_reference(name, prepare, call):
    accelerated, reference = _best_of((fast, prepare, call), (slow, prepare, call))
    ratio = accelerated / reference
    assert ratio <= MAX_RATIO, (
        f"{name} takes {ratio:.2f}x the pure-Python reference's time "
        f"({accelerated * 1e6:.2f}us against {reference * 1e6:.2f}us); the bar "
        f"is {MAX_RATIO}. It is a hard dependency whose only purpose is to be "
        f"faster. Either the Rust has a defect — `sort_ids_by_cache` once reached "
        f"1.16x by dispatching on a column type it had already decided — or the "
        f"boundary costs more than the work, in which case drop the export and "
        f"keep the reference, as `scalar_cache_get` did."
    )


@pytest.mark.parametrize(
    ("name", "prepare", "call"), CASES, ids=[case[0] for case in CASES]
)
def test_both_sides_compute_the_same_thing(name, prepare, call):
    assert call(fast, prepare()) == call(slow, prepare())


def test_fast_clone_also_beats_the_deepcopy_it_replaced():
    blob = _shared(_BLOB)
    accelerated, deepcopy_time = _best_of(
        (fast, blob, lambda m, args: m.fast_clone(*args)),
        (copy, blob, lambda m, args: m.deepcopy(*args)),
    )
    assert accelerated < deepcopy_time / 2, (
        f"fast_clone is {accelerated * 1e6:.2f}us against copy.deepcopy's "
        f"{deepcopy_time * 1e6:.2f}us; it replaced deepcopy on the strength of a "
        f"large margin and no longer has one"
    )


def test_every_accelerated_function_is_measured():
    measured = {case[0] for case in CASES}
    exported = {name for name in fast.__all__ if callable(getattr(fast, name, None))}
    assert exported == measured, (
        f"accelerated functions with no measurement: {sorted(exported - measured)}; "
        f"measured but no longer exported: {sorted(measured - exported)}"
    )
    assert measured <= set(vars(slow)), (
        f"no reference for {sorted(measured - set(vars(slow)))}"
    )


def test_the_field_access_references_are_the_production_ones():
    for name in (
        "batch_cache_fill",
        "batch_cache_filter",
        "batch_cache_get",
        "batch_group_ids",
        "sort_ids_by_cache",
        "to_prefetch_ids",
    ):
        reference = getattr(slow, name)
        assert reference.__module__.endswith("_fallback"), (
            f"{name}'s reference is {reference.__module__}, not _fallback — a "
            f"benchmark-only copy is not held to _fallback's correctness tests"
        )
