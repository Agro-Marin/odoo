import uuid

from odoo import fields, models


def _new_access_token():
    return str(uuid.uuid4())


class MixinPosBus(models.AbstractModel):
    _name = "mixin.pos.bus"
    _description = "Bus Mixin"

    access_token = fields.Char(
        "Security Token", copy=False, default=lambda self: _new_access_token()
    )

    def _get_access_token(self):
        self.ensure_one()
        if self.access_token:
            return self.access_token
        token = _new_access_token()
        self.sudo().access_token = token
        return token

    def _notify(self, *notifications, private=True) -> None:
        self.ensure_one()
        token = self._get_access_token()
        if isinstance(notifications[0], str):
            if len(notifications) != 2:
                raise ValueError(
                    "If you want to send a single notification, you must provide a name: str and a message: any"
                )
            notifications = [notifications]
        for name, message in notifications:
            self.env["bus.bus"]._sendone(
                token,
                f"{token}-{name}" if private else name,
                message,
            )
