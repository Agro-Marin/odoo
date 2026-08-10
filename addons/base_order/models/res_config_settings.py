from odoo import models
from odoo.tools.translate import _


class ResConfigSettings(models.TransientModel):
    """Settings-page helpers shared by the order types.

    Sale and purchase each expose the same two order settings — how long a new
    quotation/RFQ stays valid, and whether confirming an order locks it — and
    each had written the same two pieces of plumbing around them. The fields
    themselves stay per order type (a company sets them independently); only the
    behaviour lives here, and the concrete modules pass their field names.
    """

    _inherit = "res.config.settings"

    def _clamp_validity_days(self, field_name, label):
        """Reset a negative validity setting to its default and warn about it.

        Negative days are already rejected by a CHECK constraint on
        ``res.company``; catching it in the onchange turns a save-time traceback
        into a message next to the field the user is editing.

        Callers pass their own already-translated ``label`` so the term is
        extracted in the module that owns it — "Quotation Validity" for sale,
        "RFQ Validity" for purchase.

        :param str field_name: Integer setting to clamp, named as on ``res.company``
        :param str label: human name of the setting, for the warning
        :return: an onchange warning dict, or ``None`` when the value was fine
        """
        self.ensure_one()
        if self[field_name] >= 0:
            return None
        self[field_name] = self.env["res.company"].default_get([field_name])[field_name]
        return {
            "warning": {
                "title": _("Warning"),
                "message": _(
                    "%(label)s is required and must be greater or equal to 0.",
                    label=label,
                ),
            },
        }

    def _sync_order_lock(self, checkbox_field, lock_field):
        """Push the "lock confirmed orders" checkbox onto the company setting.

        The settings page shows a boolean while ``res.company`` stores
        ``edit``/``lock``. They are reconciled at save time rather than through
        an inverse because the checkbox's own default reads the company back,
        and an inverse would make that a write-during-default.

        :param str checkbox_field: Boolean field on the settings form
        :param str lock_field: related Selection field carrying ``edit``/``lock``
        """
        self.ensure_one()
        lock = "lock" if self[checkbox_field] else "edit"
        if self[lock_field] != lock:
            self[lock_field] = lock
