from odoo.orm.components.cache import FieldCache


def _cache():
    calls = []
    cache = FieldCache(on_detach=lambda: calls.append(1))
    parent = cache.get_field_data("f")
    sub = parent.setdefault(("en_US",), {})
    sub[1] = "v1"
    sub[2] = "v2"
    return cache, sub, calls


def test_invalidate_all_ids_notifies_the_detach_hook():
    cache, _sub, calls = _cache()
    cache.invalidate_field("f", None)
    assert calls, (
        "invalidate_field(field, None) emptied the mapping without calling "
        "on_detach, so every memoised sub-cache is now an orphan"
    )


def test_invalidate_all_ids_leaves_no_reachable_stale_value():
    cache, sub, _calls = _cache()
    cache.invalidate_field("f", None)
    assert cache.get_field_data("f") == {}
    assert cache.get_field_data("f").get(("en_US",)) is not sub


def test_invalidate_all_ids_clears_the_values():
    cache, sub, _calls = _cache()
    cache.invalidate_field("f", None)
    assert not sub, "the sub-cache kept its pre-invalidation values"


def test_invalidate_some_ids_still_prunes_and_notifies():
    cache, sub, calls = _cache()
    cache.invalidate_field("f", [1])
    assert sub == {2: "v2"}
    assert not calls, "nothing was detached, so the hook must stay quiet"
    cache.invalidate_field("f", [2])
    assert calls, "emptying the last sub-cache detaches it"


def test_flat_cache_keeps_its_identity_so_no_detach_is_needed():
    calls = []
    cache = FieldCache(on_detach=lambda: calls.append(1))
    flat = cache.get_field_data("g")
    flat[1] = "v"
    cache.invalidate_field("g", None)
    assert cache.get_field_data("g") is flat
    assert not calls
