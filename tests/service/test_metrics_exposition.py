import math

import pytest

from odoo.service import metrics


def _samples(text):
    return [l for l in text.splitlines() if l and not l.startswith("#")]


def _family_of(line):
    return line.split("{")[0].split(" ")[0]


def _declared(text):
    return {l.split()[2] for l in text.splitlines() if l.startswith("# TYPE ")}


def _owning_family(name, declared):
    """A histogram's `_bucket`/`_sum`/`_count` samples belong to its family.

    Contiguity is a property of the FAMILY, so the suffixed sample names have
    to be folded back into it before the check -- otherwise two series of one
    histogram look like an interleave when they are the correct rendering.
    """
    if name in declared:
        return name
    for suffix in ("_bucket", "_sum", "_count"):
        if name.endswith(suffix) and name[: -len(suffix)] in declared:
            return name[: -len(suffix)]
    return name


def _non_contiguous(text):
    declared = _declared(text)
    seen, prev, broken = set(), None, []
    for line in _samples(text):
        name = _owning_family(_family_of(line), declared)
        if name != prev:
            if name in seen:
                broken.append(name)
            seen.add(name)
        prev = name
    return sorted(set(broken))


_HEALTH = {
    "pool": {
        "borrows": 5,
        "pools": 2,
        "borrow_wait_seconds": {"le_+Inf": 3, "le_0.001": 1, "le_0.1": 2},
        "borrow_wait_seconds_total": 0.5,
        "borrow_wait_seconds_max": 0.2,
    },
    "backends": 4,
}


@pytest.fixture
def two_pools():
    exp = metrics._Exposition({"pid": "1"})
    metrics._add_pool_family(exp, "read_write", _HEALTH)
    metrics._add_pool_family(exp, "read_only", _HEALTH)
    return exp.render()


class TestFamiliesStayInOneBlock:
    def test_a_second_pool_does_not_split_any_family(self, two_pools):
        assert _non_contiguous(two_pools) == [], (
            "the text exposition wants every sample of a family emitted "
            "together after its HELP/TYPE; a split family loses its type for "
            "every sample after the break, and a split histogram stops being "
            "a histogram"
        )

    def test_every_family_is_typed_exactly_once(self, two_pools):
        types = [l for l in two_pools.splitlines() if l.startswith("# TYPE ")]
        names = [l.split()[2] for l in types]
        assert len(names) == len(set(names))

    def test_both_pools_are_present_for_every_family(self, two_pools):
        by_family = {}
        for line in _samples(two_pools):
            by_family.setdefault(_family_of(line), set()).add(
                "read_only" if 'pool="read_only"' in line else "read_write"
            )
        for family, pools in by_family.items():
            assert pools == {"read_write", "read_only"}, f"{family} lost a pool"

    def test_every_sample_belongs_to_a_declared_family(self, two_pools):
        declared = _declared(two_pools)
        for line in _samples(two_pools):
            name = _family_of(line)
            assert _owning_family(name, declared) in declared, (
                f"{name} is emitted with no TYPE of its own and no owning family"
            )


class TestHistogramShape:
    def test_buckets_ascend_and_end_at_positive_infinity(self, two_pools):
        runs = {}
        for line in _samples(two_pools):
            if "_bucket{" not in line:
                continue
            series = line.split(",le=")[0]
            edge = line.split('le="')[1].split('"')[0]
            runs.setdefault(series, []).append(edge)
        assert runs
        for series, edges in runs.items():
            values = [math.inf if e == "+Inf" else float(e) for e in edges]
            assert values == sorted(values), f"{series} buckets are out of order"
            assert edges[-1] == "+Inf", f"{series} has no +Inf bucket last"

    def test_sum_and_count_follow_their_own_series_buckets(self, two_pools):
        lines = _samples(two_pools)
        for pool in ("read_write", "read_only"):
            block = [
                l
                for l in lines
                if _family_of(l).startswith(metrics._BORROW_WAIT)
                and not _family_of(l).endswith("_max")
                and f'pool="{pool}"' in l
            ]
            assert "_bucket" in block[0]
            assert block[-2].startswith(f"{metrics._BORROW_WAIT}_sum")
            assert block[-1].startswith(f"{metrics._BORROW_WAIT}_count")

    def test_an_unsorted_bucket_dict_is_still_rendered_ascending(self):
        exp = metrics._Exposition()
        exp.declare(metrics._BORROW_WAIT, "histogram")
        for edge in ("le_+Inf", "le_1.0", "le_0.001"):
            exp.sample(f"{metrics._BORROW_WAIT}_bucket", 1, labels={"le": edge[3:]})
        edges = [l.split('le="')[1].split('"')[0] for l in _samples(exp.render())]
        assert edges == ["0.001", "1.0", "+Inf"]


class TestValueFormatting:
    @pytest.mark.parametrize(
        ("value", "rendered"),
        [
            (float("inf"), "+Inf"),
            (float("-inf"), "-Inf"),
            (float("nan"), "NaN"),
            (True, "1"),
            (False, "0"),
            (3, "3"),
            (0.25, "0.25"),
        ],
    )
    def test_special_floats_use_the_exposition_spelling(self, value, rendered):
        exp = metrics._Exposition()
        exp.add("m", value)
        assert _samples(exp.render()) == [f"m {rendered}"]


class TestUndeclaredSamplesAreNotDropped:
    def test_a_sample_with_no_declaration_gets_an_untyped_family(self):
        exp = metrics._Exposition()
        exp.sample("stray", 1)
        text = exp.render()
        assert "# TYPE stray untyped" in text
        assert "stray 1" in _samples(text)
