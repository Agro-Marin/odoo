from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.tools.misc import PENDING

_MOD = "test_get_column_update_pending"


class Thing(models.Model):
    _name = "gcup.thing"
    _module = _MOD
    _description = "thing"
    _log_access = False

    name = fields.Char()
    per_branch = fields.Char(compute="_compute_per_branch", store=True, readonly=False)

    @api.depends("name")
    @api.depends_context("branch")
    def _compute_per_branch(self):
        for record in self:
            record.per_branch = (record.name or "") + "!"


def _create_in_a_write_in_b(env):
    env_a = env(context={"branch": "a"})
    env_b = env(context={"branch": "b"})
    record = env_a["gcup.thing"].create({"name": "a"})
    record_b = record.with_env(env_b)
    record_b.write({"per_branch": "manual"})
    return record_b


def test_real_value_outranks_pending_in_another_context():
    with model_test_env(Thing) as env:
        record_b = _create_in_a_write_in_b(env)
        field = record_b._fields["per_branch"]

        raw = env._core.get_field_data(field)
        assert any(PENDING in sub.values() for sub in raw.values()), (
            "test premise lost: no context holds PENDING"
        )
        assert field.get_column_update(record_b) == "manual"


def test_write_survives_the_flush():
    with model_test_env(Thing) as env:
        record_b = _create_in_a_write_in_b(env)
        env.flush_all()
        env.invalidate_all()
        assert record_b.per_branch == "manual"


def test_all_pending_hands_the_dirty_flag_back():
    with model_test_env(Thing) as env:
        record = env["gcup.thing"].create({"name": "a"})
        field = record._fields["per_branch"]

        for sub_cache in env._core.get_field_data(field).values():
            sub_cache[record.id] = PENDING
        env._core.mark_dirty(field, (record.id,))

        assert field.get_column_update(record) is PENDING
        env["gcup.thing"]._flush()
        assert env._core.get_dirty(field) == {record.id}
