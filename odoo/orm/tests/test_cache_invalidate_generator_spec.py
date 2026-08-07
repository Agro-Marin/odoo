from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_cache_invalidate_generator"


class GWidget(models.Model):
    _name = "g.widget"
    _module = _MOD
    _description = "Generator-spec Widget"

    name = fields.Char()


def _cached_widget(env):
    rec = env["g.widget"].create({"name": "a"})
    env.flush_all()
    assert rec.name == "a"
    field = rec._fields["name"]
    assert env.cache.contains(rec, field)
    return rec, field


def test_invalidate_list_spec_drops_the_value():
    with model_test_env(GWidget) as env:
        rec, field = _cached_widget(env)
        env.cache.invalidate([(field, rec._ids)])
        assert not env.cache.contains(rec, field)


def test_invalidate_generator_spec_drops_the_value():
    with model_test_env(GWidget) as env:
        rec, field = _cached_widget(env)
        env.cache.invalidate((f, rec._ids) for f in [field])
        assert not env.cache.contains(rec, field)
