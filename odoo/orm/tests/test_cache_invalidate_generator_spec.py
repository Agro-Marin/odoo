"""``Cache.invalidate`` must not silently no-op on a generator ``spec``.

``runtime/cache_compat.py::Cache.invalidate`` walks ``spec`` twice — once for
the pending-write guard, once to invalidate.  A generator argument is exhausted
by the guard pass, so the work pass sees nothing: the call returns successfully
and every value stays cached.  The same subsystem defends against this exact
hazard twice (``components/core.py`` and ``components/cache.py`` both
materialize one-shot iterables, with docstrings explaining why), but the
recordset-level entry point does not.

The first test pins the working list-``spec`` behaviour; the strict-xfail pins
the defect and will flip to a hard failure the moment someone fixes the double
iteration (then delete the xfail decorator).
"""

import pytest

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
    assert rec.name == "a"  # ensure the value is in cache
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
