from odoo.orm.primitives import NewId


class TestNewIdOrdersAfterItsOrigin:
    def test_is_not_below_or_equal_to_its_own_origin(self):
        new = NewId(5)
        assert not new < 5
        assert not new <= 5
        assert new > 5
        assert new >= 5

    def test_sits_between_its_origin_and_the_next_integer(self):
        new = NewId(5)
        assert new > 4
        assert new < 6
        assert new <= 6

    def test_is_never_equal_to_its_origin(self):
        assert NewId(5) != 5
        assert (NewId(5) == 5) is False

    def test_orders_against_another_newid_by_origin(self):
        assert NewId(5) < NewId(9)
        assert NewId(9) > NewId(5)
        assert NewId(5) == NewId(5)

    def test_an_origin_less_newid_sorts_after_everything(self):
        anonymous, real = NewId(), NewId(5)
        assert not anonymous < real
        assert anonymous > real
        assert real < anonymous

    def test_sorting_a_mixed_list_interleaves_each_newid_after_its_origin(self):
        anonymous = NewId()
        values = [9, NewId(5), 5, NewId(9), 3, anonymous]
        assert sorted(values) == [3, 5, NewId(5), 9, NewId(9), anonymous]

    def test_lt_and_ge_are_consistent_complements(self):
        subjects = [NewId(5), NewId(9), NewId()]
        others = [3, 5, 9, NewId(5), NewId(9)]
        for left in subjects:
            for right in others:
                assert (left < right) != (left >= right), (left, right)


class TestNewIdTrichotomyGap:
    def test_two_anonymous_newids_are_neither_equal_nor_ordered(self):
        one, two = NewId(), NewId()
        assert (one == two) is False
        assert not one < two
        assert not one > two

    def test_an_anonymous_newid_equals_itself(self):
        one = NewId()
        assert one == one
        assert one <= one
        assert one >= one


class TestNewIdIdentity:
    def test_is_always_falsy(self):
        assert not NewId()
        assert not NewId(5)

    def test_equality_follows_origin_then_ref(self):
        assert NewId(origin=5) == NewId(origin=5)
        assert NewId(ref="a") == NewId(ref="a")
        assert NewId(ref="a") != NewId(ref="b")

    def test_hash_matches_equality_where_equality_holds(self):
        assert hash(NewId(origin=5)) == hash(NewId(origin=5))
        assert hash(NewId(ref="a")) == hash(NewId(ref="a"))
