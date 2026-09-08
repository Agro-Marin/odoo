from odoo import fields, models


class ResUsersLoginCooldown(models.Model):
    _name = "res.users.login.cooldown"
    _description = "Login Failure Cooldown"
    _log_access = False

    source = fields.Char(required=True, index="btree")
    failures = fields.Integer(required=True, default=0)
    last_failure = fields.Datetime(required=True, index="btree")

    _source_uniq = models.Constraint(
        "unique (source)",
        "There can be only one cooldown row per source.",
    )
