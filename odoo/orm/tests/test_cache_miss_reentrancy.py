"""Regression: ``Field._get_cache_miss`` must re-resolve the cache dict.

Every miss branch runs re-entrant code before its terminal read -- ``_fetch_field``
(flush -> recompute -> a compute may call ``env.invalidate_all()``), reading an
``_origin`` value, or ``default_get`` (arbitrary user code). ``invalidate_all``
*detaches* the per-field cache dict (the outer ``_data`` map is cleared / the key
deleted), so a dict captured before that code runs no longer receives the fresh
value -- it lands in a new dict. Reading the captured dict then raises a spurious
``MissingError`` (store branch), ``KeyError`` (origin branch) or silently returns
the stale null pre-write (default branch). Only the compute branch re-resolved;
these lock the fix for the other three. Tier-2 suite: real ``import odoo``, no
database -- run like ``test_model_test_env``.
"""

import sys

import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_cache_miss_reentrancy"


class CacheMissThing(models.Model):
    _name = "cache.miss.thing"
    _module = _MOD
    _description = "default-branch model"

    name = fields.Char()
    color = fields.Char()

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("boom_default"):
            # user code inside default_get invalidating caches
            self.env.invalidate_all(flush=False)
            if "color" in fields_list:
                res["color"] = "red"
        return res


class CacheMissReal(models.Model):
    _name = "cache.miss.real"
    _module = _MOD
    _description = "store-branch model with a pending compute"

    name = fields.Char()
    tick = fields.Integer()
    shadow = fields.Integer(compute="_compute_shadow", store=True)

    @api.depends("tick")
    def _compute_shadow(self):
        for rec in self:
            if rec.env.context.get("boom_compute"):
                rec.env.invalidate_all(flush=False)
            rec.shadow = (rec.tick or 0) + 1


def test_default_branch_survives_invalidation_in_default_get():
    with model_test_env(CacheMissThing, CacheMissReal) as env:
        rec = env["cache.miss.thing"].with_context(boom_default=True).new({})
        # Before the fix: the null pre-write lands in the captured dict while the
        # real default "red" lands in the new one, so the first read is a stale
        # False (silent wrong value).
        assert rec.color == "red"


def test_store_branch_survives_invalidation_inside_fetch(monkeypatch):
    with model_test_env(CacheMissThing, CacheMissReal) as env:
        rec = env["cache.miss.real"].create({"name": "hello", "tick": 1})
        rec_id = rec.id
        env.invalidate_all(flush=True)
        rec = env["cache.miss.real"].browse(rec_id)

        model_cls = type(env["cache.miss.real"])
        orig_fetch = model_cls._fetch_field

        def boom_fetch(self, field):
            # flush -> recompute -> a compute calling env.invalidate_all()
            self.env.invalidate_all(flush=False)
            return orig_fetch(self, field)

        monkeypatch.setattr(model_cls, "_fetch_field", boom_fetch)
        # Before the fix: MissingError raised for a record that exists.
        assert rec.name == "hello"


def test_store_branch_realistic_pending_compute_invalidates():
    with model_test_env(CacheMissThing, CacheMissReal) as env:
        rec = env["cache.miss.real"].create({"name": "hello", "tick": 1})
        rec_id = rec.id
        env.cr.flush()
        # make 'shadow' pending again and its compute invalidate everything, then
        # force a DB fetch of 'name' whose flush triggers that recompute
        rec.write({"tick": 2})
        rec.invalidate_recordset(["name"])
        rec2 = env["cache.miss.real"].browse(rec_id).with_context(boom_compute=True)
        assert rec2.name == "hello"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
