import pytest

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.orm.model_test_env import model_test_env

_MOD = "test_rec_names_search_cycle"


class CycleA(models.Model):
    _name = "cycle.a"
    _module = _MOD
    _description = "Cycle A"
    _rec_names_search = ["b_id"]

    name = fields.Char()
    b_id = fields.Many2one("cycle.b")


class CycleB(models.Model):
    _name = "cycle.b"
    _module = _MOD
    _description = "Cycle B"
    _rec_names_search = ["a_id"]

    name = fields.Char()
    a_id = fields.Many2one("cycle.a")


class PartCycle(models.Model):
    _name = "part.cycle"
    _module = _MOD
    _description = "Partly Cyclic"
    _rec_names_search = ["name", "self_id"]

    name = fields.Char()
    self_id = fields.Many2one("part.cycle")


@pytest.fixture
def env():
    gen = model_test_env(CycleA, CycleB, PartCycle)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_a_fully_cyclic_rec_names_search_raises_instead_of_matching_everything(env):
    with pytest.raises(UserError, match="recurses back into"):
        env["cycle.a"]._search_display_name("ilike", "zzz")


def test_a_partly_cyclic_rec_names_search_uses_the_acyclic_entries(env):
    env["part.cycle"].create([{"name": "match"}, {"name": "other"}])
    domain = env["part.cycle"]._search_display_name("ilike", "match")
    found = env["part.cycle"].search(domain)
    assert found.mapped("name") == ["match"]
