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

    def default_get(self, fields):
        res = super().default_get(fields)
        if self.env.context.get("boom_default"):
            self.env.invalidate_all(flush=False)
            if "color" in fields:
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
            self.env.invalidate_all(flush=False)
            return orig_fetch(self, field)

        monkeypatch.setattr(model_cls, "_fetch_field", boom_fetch)
        assert rec.name == "hello"


def test_store_branch_realistic_pending_compute_invalidates():
    with model_test_env(CacheMissThing, CacheMissReal) as env:
        rec = env["cache.miss.real"].create({"name": "hello", "tick": 1})
        rec_id = rec.id
        env.cr.flush()
        rec.write({"tick": 2})
        rec.invalidate_recordset(["name"])
        rec2 = env["cache.miss.real"].browse(rec_id).with_context(boom_compute=True)
        assert rec2.name == "hello"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
