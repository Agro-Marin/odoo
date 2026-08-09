# Part of Odoo. See LICENSE file for full copyright and licensing details.

import uuid

from odoo import fields, models


def _new_access_token():
    # uuid4 is os.urandom-backed. This token is the sole credential for the
    # public /pos/ticket/validate route and for every bus channel below, so it
    # must never be derived from anything guessable (nor accepted from a
    # client -- see PosOrder._process_order).
    return str(uuid.uuid4())


class PosBusMixin(models.AbstractModel):
    _name = "pos.bus.mixin"
    _description = "Bus Mixin"

    # Minted by the column default so it lands in the same INSERT. The lazy
    # `_get_access_token` below stays for rows that predate this default.
    access_token = fields.Char(
        "Security Token", copy=False, default=lambda self: _new_access_token()
    )

    def _get_access_token(self):
        """This record's bus/portal token, minting one on first use.

        Elevated on purpose: the token is infrastructure, not data the caller
        is editing. A cashier holds read-only access to `pos.config`
        (`access_pos_config_user`) yet has to open a bus channel on it, so
        without `sudo()` every notification path would raise AccessError.
        The write is a keyhole -- one field, on one record, never from client
        input.
        """
        self.ensure_one()
        if self.access_token:
            return self.access_token
        token = _new_access_token()
        self.sudo().access_token = token
        return token

    def _notify(self, *notifications, private=True) -> None:
        """Send a notification to the bus.
        ex: one notification: ``self._notify('STATUS', {'status': 'closed'})``
        multiple notifications: ``self._notify(('STATUS', {'status': 'closed'}), ('TABLE_ORDER_COUNT', {'count': 2}))``
        """
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
