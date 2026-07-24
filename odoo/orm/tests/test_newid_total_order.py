"""The documented total-order and identity table of :class:`odoo.orm.primitives.NewId`.

Tier-2 suite (real ``import odoo``, no database — run as ``pytest
odoo/orm/tests``).  The ordering contract — ``NewId(N)`` sorts as ``N + 0.5``,
``NewId()`` as ``+infinity``, two distinct ``NewId()`` mutually incomparable —
was previously locked only by the DB-backed ``test_orm.test_sort``; this pins
it DB-free, together with the equality/hash rules for origin- and
ref-carrying NewIds that record sorting and cache keying rely on.
"""

import pytest

from odoo.orm.primitives import NewId


class TestNewIdVsInt:
    def test_origin_newid_sits_between_n_and_n_plus_1(self):
        n = NewId(origin=5)
        # N + 0.5 relative to int N: strictly greater
        assert n > 5
        assert n >= 5
        assert not n < 5
        assert not n <= 5
        # int on the LEFT on purpose: int.__lt__ returns NotImplemented for a
        # NewId, so these exercise the reflected __gt__/__ge__ dispatch
        assert 5 < n  # noqa: SIM300
        assert 5 <= n  # noqa: SIM300
        # N + 0.5 relative to int N+1: strictly smaller
        assert n < 6
        assert n <= 6
        assert not n > 6
        assert not n >= 6
        # reflected dispatch again (see above)
        assert 6 > n  # noqa: SIM300
        assert 6 >= n  # noqa: SIM300

    def test_originless_newid_is_plus_infinity_vs_int(self):
        n = NewId()
        for value in (-1, 0, 10**9):
            assert n > value
            assert n >= value
            assert not n < value
            assert not n <= value


class TestNewIdVsNewId:
    def test_origin_newids_compare_by_origin(self):
        assert NewId(origin=1) < NewId(origin=2)
        assert NewId(origin=1) <= NewId(origin=2)
        assert NewId(origin=2) > NewId(origin=1)
        assert NewId(origin=2) >= NewId(origin=1)
        assert not NewId(origin=2) < NewId(origin=1)

    def test_equal_origin_newids_are_le_and_ge_but_not_lt(self):
        a, b = NewId(origin=5), NewId(origin=5)
        assert a == b
        assert a <= b
        assert a >= b
        assert not a < b
        assert not a > b

    def test_origin_newid_below_originless(self):
        finite, inf = NewId(origin=10**9), NewId()
        assert finite < inf
        assert finite <= inf
        assert inf > finite
        assert inf >= finite
        assert not inf < finite
        assert not inf <= finite

    def test_two_distinct_originless_newids_are_incomparable(self):
        a, b = NewId(), NewId()
        assert not a < b
        assert not a > b
        assert not a <= b
        assert not a >= b
        assert a != b

    def test_originless_newid_is_comparable_to_itself(self):
        a = NewId()
        assert a <= a
        assert a >= a
        assert not a < a
        assert not a > a


class TestSorting:
    def test_sorted_interleaves_origin_newids_with_ints(self):
        items = [NewId(origin=2), 1, NewId(), 3, NewId(origin=1)]
        assert sorted(items) == [
            1,
            items[4],  # NewId(1) at 1.5
            items[0],  # NewId(2) at 2.5
            3,
            items[2],  # NewId() at +inf
        ]

    def test_sort_is_stable_for_int_before_equal_origin(self):
        # int N sorts before NewId(N) (N < N + 0.5), regardless of input order
        n = NewId(origin=5)
        assert sorted([n, 5]) == [5, n]
        assert sorted([5, n]) == [5, n]

    def test_sort_is_stable_for_incomparable_originless_newids(self):
        # all comparisons between distinct NewId() are False, so sorted() keeps
        # their input order (Timsort stability)
        a, b, c = NewId(), NewId(), NewId()
        result = sorted([b, a, c])
        assert result == [b, a, c]
        assert [id(x) for x in result] == [id(b), id(a), id(c)]


class TestEqualityHashAndOrigin:
    def test_equality_rules(self):
        assert NewId(origin=5) == NewId(origin=5)
        assert NewId(origin=5) != NewId(origin=6)
        # an origin-set NewId is never equal to an origin-less one
        assert NewId(origin=5) != NewId()
        assert NewId() != NewId(origin=5)
        # both origins None: refs decide (when both set)
        assert NewId(ref="r") == NewId(ref="r")
        assert NewId(ref="r") != NewId(ref="s")
        # origin takes precedence over ref: one side origin-set, no match
        assert NewId(origin=5, ref="r") != NewId(ref="r")
        # same identity is always equal
        n = NewId()
        assert n == n

    def test_equality_against_non_newid_is_false(self):
        # __eq__ returns NotImplemented for non-NewId; == then falls back to
        # identity, so a NewId never equals its origin int
        assert NewId(origin=5) != 5
        assert NewId() != False  # noqa: E712 — the comparison IS the test

    def test_hash_follows_origin_then_ref(self):
        assert hash(NewId(origin=5)) == hash(NewId(origin=5)) == hash(5)
        assert hash(NewId(ref="r")) == hash(NewId(ref="r")) == hash("r")
        # a == b implies hash(a) == hash(b) for the mixed origin/ref case too
        assert hash(NewId(origin=5, ref="zzz")) == hash(NewId(origin=5))

    def test_origin_zero_is_set_not_absent(self):
        # falsy origin (0) still counts as "origin set" for eq/repr
        assert NewId(origin=0) == NewId(origin=0)
        assert NewId(origin=0) != NewId()
        assert repr(NewId(origin=0)) == "<NewId origin=0>"

    def test_newid_is_always_falsy(self):
        assert not NewId()
        assert not NewId(origin=7)
        assert not NewId(ref="r")

    def test_comparison_with_unsupported_type_raises(self):
        with pytest.raises(TypeError):
            NewId() < "abc"  # noqa: B015 — evaluating the comparison IS the test
