from odoo import models
from odoo.tools import frozendict


class AccountMoveSendBatchWizard(models.TransientModel):
    _inherit = "account.move.send.batch.wizard"

    _access_anchors = frozendict(
        {
            "owner": models.Anchor("move_ids.invoice_user_id", shared=True),
        }
    )


class AccountMoveSendWizard(models.TransientModel):
    _inherit = "account.move.send.wizard"

    _access_anchors = frozendict(
        {
            "owner": models.Anchor("move_id.invoice_user_id", shared=True),
        }
    )
