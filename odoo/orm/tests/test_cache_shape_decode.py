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
