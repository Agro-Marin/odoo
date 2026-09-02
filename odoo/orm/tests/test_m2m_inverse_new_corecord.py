import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_m2m_inverse_new_corecord"


class TagOwner(models.Model):
    _name = "tag.owner"
    _module = _MOD
    _description = "Tag Owner"

    name = fields.Char()
    tag_ids = fields.Many2many("tag.tag", "owner_tag_rel", "owner_id", "tag_id")


class Tag(models.Model):
    _name = "tag.tag"
    _module = _MOD
    _description = "Tag"

    name = fields.Char()
    owner_ids = fields.Many2many("tag.owner", "owner_tag_rel", "tag_id", "owner_id")


@pytest.fixture
def env():
    gen = model_test_env(TagOwner, Tag)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_linking_a_new_corecord_seeds_its_inverse(env):
    owner = env["tag.owner"].new({"name": "o"})
    tag = env["tag.tag"].new({"name": "t"})
    owner.tag_ids = [(4, tag.id)]

    assert owner in tag.owner_ids, (
        "the symmetric m2m on a NEW corecord never learned of the link -- "
        "there is no database row for it to fall back to"
    )
