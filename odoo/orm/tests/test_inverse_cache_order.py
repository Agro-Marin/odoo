from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_inverse_cache_order"


class Parent(models.Model):
    _name = "ico.parent"
    _module = _MOD
    _description = "parent"
    _log_access = False

    name = fields.Char()
    child_ids = fields.One2many("ico.child", "parent_id")
    id_child_ids = fields.One2many("ico.id.child", "parent_id")
    note_ids = fields.One2many(
        "ico.note", "res_id", domain=[("res_model", "=", "ico.parent")]
    )


class Child(models.Model):
    _name = "ico.child"
    _module = _MOD
    _description = "child ordered by name, descending"
    _log_access = False
    _order = "name desc"

    name = fields.Char()
    parent_id = fields.Many2one("ico.parent")


class IdChild(models.Model):
    _name = "ico.id.child"
    _module = _MOD
    _description = "child ordered by id"
    _log_access = False

    name = fields.Char()
    parent_id = fields.Many2one("ico.parent")


class Note(models.Model):
    _name = "ico.note"
    _module = _MOD
    _description = "note ordered by body, descending"
    _log_access = False
    _order = "body desc"

    body = fields.Char()
    res_model = fields.Char()
    res_id = fields.Many2oneReference(model_field="res_model")


def _env():
    return model_test_env(Parent, Child, IdChild, Note)


def test_children_created_out_of_order_read_back_in_the_comodel_order():
    with _env() as env:
        parent = env["ico.parent"].create({"name": "p"})
        assert parent.child_ids.ids == []

        env["ico.child"].create({"name": "a", "parent_id": parent.id})
        env["ico.child"].create({"name": "z", "parent_id": parent.id})

        assert parent.child_ids.mapped("name") == ["z", "a"]


def test_a_child_moved_by_write_reads_back_in_the_new_parents_order():
    with _env() as env:
        first, second = env["ico.parent"].create([{"name": "1"}, {"name": "2"}])
        moved = env["ico.id.child"].create({"name": "moved", "parent_id": first.id})
        stayed = env["ico.id.child"].create({"name": "stayed", "parent_id": second.id})
        assert second.id_child_ids.ids == [stayed.id]

        moved.parent_id = second

        assert second.id_child_ids.ids == [moved.id, stayed.id]


def test_an_id_ordered_create_keeps_the_parents_cached_children():
    with _env() as env:
        parent = env["ico.parent"].create({"name": "p"})
        assert parent.id_child_ids.ids == []
        field = env["ico.parent"]._fields["id_child_ids"]

        child = env["ico.id.child"].create({"name": "c", "parent_id": parent.id})

        assert parent.id in field._get_cache(env)
        assert parent.id_child_ids.ids == [child.id]


def test_notes_created_through_a_reference_read_back_in_the_comodel_order():
    with _env() as env:
        parent = env["ico.parent"].create({"name": "p"})
        assert parent.note_ids.ids == []

        for body in ("a", "z"):
            env["ico.note"].create(
                {"body": body, "res_model": "ico.parent", "res_id": parent.id}
            )

        assert parent.note_ids.mapped("body") == ["z", "a"]
