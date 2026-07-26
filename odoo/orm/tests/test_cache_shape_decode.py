"""Every consumer of a context-dependent field's cache must decode its shape
the same way the cache itself does.

``FieldCache`` keeps a context-dependent field as ``{context_key: {id: value}}``
and guards its own accessors with ``isinstance(key, tuple)``, because a field
can also carry a flat ``{id: value}`` entry written while it was not yet
context-dependent.  Three consumers in ``env.cache`` re-implemented that decode
without the guard, so on such a cache ``get_records(all_contexts=True)``
iterated a *scalar value* and returned a recordset of its characters,
``repr(env.cache)`` raised ``AttributeError``, and ``check()`` fed the scalar to
a strict ``zip``.

Reachability, measured rather than assumed: the mixed shape could not be
produced through ``_setup_models__`` (incremental or full) nor through a full
``-u base`` upgrade of a 154-module database with a probe on
``Field._get_cache_impl`` (zero flat resolutions of a context-dependent field),
and ``all_contexts=True`` has no caller outside these tests.  These are
consistency guards, not a reproduced production failure: they pin the three
consumers to the cache's own accessors so the shape rule has one owner.
"""

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_cache_shape_decode"


class Thing(models.Model):
    _name = "csd.thing"
    _module = _MOD
    _description = "thing"
    _log_access = False

    name = fields.Char()
    scoped = fields.Char(depends_context=("scheme",))


def _env():
    return model_test_env(Thing)


def _cache_with_stale_flat_entry(env, field, record):
    record.scoped = "value-in-context"
    raw = env._core.get_field_data(field)
    assert any(isinstance(key, tuple) for key in raw), raw
    raw[10**9] = "stale-flat-value"
    return raw


def test_get_records_all_contexts_ignores_stale_flat_entry():
    with _env() as env:
        field = env["csd.thing"]._fields["scoped"]
        assert field in env.registry.field_depends_context
        rec = env["csd.thing"].create({"name": "a"})
        _cache_with_stale_flat_entry(env, field, rec)

        records = env.cache.get_records(env["csd.thing"], field, all_contexts=True)

        assert records.ids == [rec.id]
        assert all(isinstance(id_, int) for id_ in records._ids)


def test_get_records_all_contexts_unions_every_context():
    with _env() as env:
        Thing_ = env["csd.thing"]
        field = Thing_._fields["scoped"]
        rec_a = Thing_.create({"name": "a"})
        rec_b = Thing_.create({"name": "b"})
        rec_a.with_context(scheme="x").scoped = "ax"
        rec_b.with_context(scheme="y").scoped = "by"

        records = env.cache.get_records(Thing_, field, all_contexts=True)

        assert set(records.ids) == {rec_a.id, rec_b.id}


def test_cache_repr_survives_a_mixed_shape_cache():
    with _env() as env:
        field = env["csd.thing"]._fields["scoped"]
        rec = env["csd.thing"].create({"name": "a"})
        _cache_with_stale_flat_entry(env, field, rec)

        text = repr(env.cache)

        assert "stale-flat-value" not in text
        assert "value-in-context" in text


def test_iter_context_caches_matches_all_cached_ids():
    with _env() as env:
        field = env["csd.thing"]._fields["scoped"]
        rec = env["csd.thing"].create({"name": "a"})
        _cache_with_stale_flat_entry(env, field, rec)

        from_pairs = {
            id_ for _key, sub in env._core.iter_context_caches(field) for id_ in sub
        }
        from_ids = set(env._core.all_cached_ids(field, context_dependent=True))

        assert from_pairs == from_ids == {rec.id}
