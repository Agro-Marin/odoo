from odoo import models
from odoo.tools import frozendict


class ResourceScheduleException(models.Model):
    _inherit = "resource.schedule.exception"

    _access_anchors = frozendict(
        {
            "owner": "resource_id.user_id",
            "owner_or_unset": models.Anchor(
                "resource_id.user_id", kind="owner", shared=True
            ),
        }
    )
