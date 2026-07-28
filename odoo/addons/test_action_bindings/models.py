from odoo import api, fields, models


class TabA(models.Model):
    _name = "tab.a"
    _description = "tab.a"


class TabB(models.Model):
    _name = "tab.b"
    _description = "tab.b"


class TabActionHolder(models.Model):
    """Owns a real reference to an action, with a real ``ondelete`` policy.

    ``ir_actions`` is a table-inheritance root, so PostgreSQL creates no
    foreign key here and ``ir.actions.actions.unlink`` has to apply the
    ``cascade`` itself.
    """

    _name = "tab.action.holder"
    _description = "tab.action.holder"

    action_id = fields.Many2one("ir.actions.actions", ondelete="cascade")


class TabActionMirror(models.Model):
    """Mirrors the holder's reference through a *stored related* field.

    Its own ``ondelete`` is ``None``: a related field never reaches
    ``Many2one.setup_nonrelated``. Treating that absence as ``set null``
    schedules a write against rows the holder's ``cascade`` has already
    destroyed.
    """

    _name = "tab.action.mirror"
    _description = "tab.action.mirror"

    holder_id = fields.Many2one("tab.action.holder", required=True, ondelete="cascade")
    action_id = fields.Many2one(
        "ir.actions.actions", related="holder_id.action_id", store=True
    )


class TabActionComputed(models.Model):
    """Points at an action through a non-stored compute with no ``search``.

    Nothing can be swept here: there is no column to null out, and the
    ``search`` a sweep would issue has no way to resolve.
    """

    _name = "tab.action.computed"
    _description = "tab.action.computed"

    holder_id = fields.Many2one("tab.action.holder")
    action_id = fields.Many2one("ir.actions.actions", compute="_compute_action_id")

    @api.depends("holder_id.action_id")
    def _compute_action_id(self) -> None:
        for record in self:
            record.action_id = record.holder_id.action_id
