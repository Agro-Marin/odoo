from typing import Any

from odoo import models


class IrAccessObligation(models.AbstractModel):
    """What a verb obliges beyond the capability to perform it.

    The kernel asks this model at every door, checkpoint and transition of a
    declared verb; the default obliges nothing. A module that attaches an
    obligation to verbs (approval) extends it.
    """

    _name = "ir.access.obligation"
    _description = "Access Obligation"

    def _at_door(self, records: models.BaseModel, verb: str, call: Any) -> Any:
        with records.env.transaction.admitting(records._name, verb, records._ids):
            return call(records)

    def _at_checkpoint(self, records: models.BaseModel, verb: str) -> None:
        return
