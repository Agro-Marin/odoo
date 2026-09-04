from odoo import fields, models


class ResUsersLoginCooldown(models.Model):
    """Durable, cross-process counter behind the login-failure cooldown.

    `res.users._assert_can_auth` reads and writes this table through its own
    short-lived cursor, independent of the caller's transaction: a failed
    login raises `AccessDenied`, which unwinds the request without
    committing, so the failure count must not live only in that transaction.
    """

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
