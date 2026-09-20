from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env


class CacheRecord(models.Model):
    _name = "readonly.cache.record"
    _module = "test_readonly_cache_inspection"
    _description = "Readonly Cache Record"
    _log_access = False

    name = fields.Char()
    contextual = fields.Char(compute="_compute_contextual")

    @api.depends_context("label")
    def _compute_contextual(self):
        for record in self:
            record.contextual = self.env.context.get("label", "default")


def test_empty_inspection_does_not_allocate_field_maps():
    with model_test_env(CacheRecord) as env:
        record = env[CacheRecord._name].browse(987654)
        env.invalidate_all()
        assert not tuple(record._cache)
        assert not list(env.core.iter_cached_fields())


def test_inspection_preserves_new_records_and_context_partitions():
    with model_test_env(CacheRecord) as env:
        record = env[CacheRecord._name].new({"name": "draft"})
        first = record.with_context(label="first")
        second = record.with_context(label="second")
        assert first.contextual == "first"
        assert "contextual" in first._cache
        assert "contextual" not in second._cache
        assert dict(first._cache)["name"] == "draft"
        assert dict(first._cache)["contextual"] == "first"
        assert "contextual" not in dict(second._cache)
        assert second.contextual == "second"
        assert dict(second._cache)["contextual"] == "second"
