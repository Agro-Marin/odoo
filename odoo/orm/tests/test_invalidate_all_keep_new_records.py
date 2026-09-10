import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_invalidate_all_keep_new_records"


class Draft(models.Model):
    _name = "x.draft"
    _module = _MOD
    _description = "draft"

    name = fields.Char()
    qty = fields.Integer()


@pytest.fixture
def env():
    with model_test_env(Draft) as e:
        yield e


def _rewrite_behind_the_cache(env, record, name):
    env.cr.storage.update_rows(env["x.draft"]._table, [(record.id, {"name": name})])


class TestKeepNewRecords:
    def test_a_new_record_keeps_its_unsaved_value(self, env):
        draft = env["x.draft"].new({"name": "unsaved"})

        env.invalidate_all(flush=False, keep_new_records=True)

        assert draft.name == "unsaved"

    def test_a_stored_record_rereads_the_database(self, env):
        stored = env["x.draft"].create({"name": "cached"})
        env.flush_all()
        assert stored.name == "cached"
        _rewrite_behind_the_cache(env, stored, "rolled back")

        env.invalidate_all(flush=False, keep_new_records=True)

        assert stored.name == "rolled back"

    def test_a_new_record_keeps_its_value_and_its_origin_rereads(self, env):
        stored = env["x.draft"].create({"name": "cached", "qty": 1})
        env.flush_all()
        draft = env["x.draft"].new({"name": "edited"}, origin=stored)
        _rewrite_behind_the_cache(env, stored, "rolled back")

        env.invalidate_all(flush=False, keep_new_records=True)

        assert draft.name == "edited"
        assert stored.name == "rolled back"

    def test_the_default_still_drops_a_new_record_value(self, env):
        draft = env["x.draft"].new({"name": "unsaved"})

        env.invalidate_all(flush=False)

        assert not draft.name

    def test_a_pending_write_survives(self, env):
        stored = env["x.draft"].create({"name": "before"})
        env.flush_all()
        stored.name = "pending"

        env.invalidate_all(flush=False, keep_new_records=True)
        env.flush_all()
        env.invalidate_all()

        assert stored.name == "pending"
