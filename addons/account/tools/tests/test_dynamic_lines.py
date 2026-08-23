from addons.account.tools.dynamic_lines import (
    filter_trivial,
    plan_dynamic_line_sync,
)


class frozendict(dict):
    __slots__ = ()

    def __hash__(self):
        return hash(frozenset(self.items()))


K1 = frozendict(move_id=1, date_maturity="2026-01-31", discount_date=False)
K2 = frozendict(move_id=1, date_maturity="2026-02-28", discount_date=False)
K3 = frozendict(move_id=2, date_maturity="2026-01-31", discount_date=False)
V1 = {"balance": 100.0, "amount_currency": 100.0}
V2 = {"balance": 60.0, "amount_currency": 60.0}


def differ_always(line, values):
    return True


def differ_never(line, values):
    return False


def plan(
    existing_before,
    existing_after,
    needed_before,
    needed_after,
    values_differ=differ_always,
):
    return plan_dynamic_line_sync(
        existing_before,
        existing_after,
        needed_before,
        needed_after,
        values_differ,
    )


def test_no_change_returns_none():
    assert plan({"a": K1}, {"a": K1}, {K1: V1}, {K1: V1}) is None


def test_manually_created_lines_are_preserved():
    assert plan({}, {"a": K1}, {}, {K1: V1}) is None


def test_technical_keys_ignored_in_manual_guard():
    before = {}
    after = {"a": frozendict(id=42)}
    result = plan(before, after, {}, {K1: V1})
    assert result is not None
    to_delete, to_create, to_write = result
    assert to_create == {K1: V1}
    assert to_delete == ["a"]
    assert to_write == {}


def test_simple_create():
    to_delete, to_create, to_write = plan(
        {"a": K1},
        {"a": K1},
        {K1: V1},
        {K1: V1, K2: V2},
        values_differ=differ_never,
    )
    assert to_create == {K2: V2}
    assert to_delete == []
    assert to_write == {}


def test_needed_key_without_line_is_created():
    _to_delete, to_create, _to_write = plan({}, {}, {K1: V1}, {K1: V1, K2: V2})
    assert to_create == {K1: V1, K2: V2}


def test_simple_delete():
    to_delete, to_create, to_write = plan(
        {"a": K1, "b": K2},
        {"a": K1, "b": K2},
        {K1: V1, K2: V2},
        {K1: V1},
        values_differ=differ_never,
    )
    assert set(to_delete) == {"b"}
    assert to_create == {}
    assert to_write == {}


def test_write_only_when_values_differ():
    args = ({"a": K1}, {"a": K1}, {K1: V1}, {K1: V2})
    _to_delete, _to_create, to_write = plan(*args, values_differ=differ_always)
    assert to_write == {"a": V2}
    _to_delete, _to_create, to_write = plan(*args, values_differ=differ_never)
    assert to_write == {}


def test_line_morphing_to_needed_key_is_kept():
    to_delete, to_create, to_write = plan({"a": K1}, {"a": K2}, {K1: V1}, {K2: V2})
    assert to_delete == []
    assert to_create == {}
    assert to_write == {"a": V2}


def test_key_takeover_after_deletion_does_not_crash():
    to_delete, to_create, to_write = plan({"a": K1}, {"b": K1}, {K1: V1}, {K2: V2})
    assert set(to_delete) == {"a", "b"}
    assert to_create == {K2: V2}
    assert to_write == {}


def test_duplicate_keys_are_merged_not_double_written():
    to_delete, to_create, to_write = plan(
        {"a": K1, "b": K1}, {"a": K1, "b": K1}, {K1: V1}, {K1: V2}
    )
    assert len(to_write) == 1
    assert list(to_write.values()) == [V2]
    kept = next(iter(to_write))
    assert set(to_delete) == {"a", "b"} - {kept}
    assert to_create == {}


def test_multi_move_no_cross_contamination():
    to_delete, to_create, to_write = plan(
        {"a": K1, "c": K3},
        {"a": K1, "c": K3},
        {K1: V1, K3: V2},
        {K3: V2},
        values_differ=differ_never,
    )
    assert to_delete == ["a"]
    assert to_create == {}
    assert to_write == {}


def test_filter_trivial():
    mapping = {"a": frozendict(id=1), "b": K1}
    assert filter_trivial(mapping) == {"b": K1}


def test_plan_never_writes_a_line_it_also_deletes():
    for existing_before, existing_after in (
        ({"a": K1, "b": K1}, {"a": K1, "b": K2}),
        ({"b": K1, "a": K1}, {"b": K2, "a": K1}),
    ):
        to_delete, _to_create, to_write = plan(
            existing_before, existing_after, {K1: V1}, {K2: V2}
        )
        assert not set(to_delete) & set(to_write)


def test_plan_does_not_depend_on_mapping_order():
    forward = plan({"a": K1, "b": K1}, {"a": K1, "b": K2}, {K1: V1}, {K2: V2})
    reverse = plan({"b": K1, "a": K1}, {"b": K2, "a": K1}, {K1: V1}, {K2: V2})
    assert sorted(forward[0]) == sorted(reverse[0])
    assert forward[1] == reverse[1]
    assert forward[2] == reverse[2]
