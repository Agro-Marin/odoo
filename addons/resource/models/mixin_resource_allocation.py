from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MixinResourceAllocation(models.AbstractModel):
    """Opt-in allocation semantics for consumers of the reservation ledger."""

    _name = "mixin.resource.allocation"
    _description = "Resource Allocation Mixin"
    _inherit = ["mixin.resource.scheduling"]

    allocated_percentage = fields.Float(
        "Allocation %",
        default=100.0,
        help="Percentage of the resource's work capacity allocated to this record.",
    )
    allocated_hours = fields.Float(
        "Allocated Hours",
        compute="_compute_allocated_hours",
        store=True,
        readonly=False,
        help="Working hours between scheduling start and end, respecting the resource calendar.",
    )

    @api.constrains("allocated_percentage")
    def _check_allocated_percentage(self):
        """Keep the allocation share inside 0..100.

        ``resource.reservation`` carries the equivalent SQL ``CHECK``, but the
        value originates here: consumers pass it straight through
        ``_get_reservation_vals_list``, so rejecting it at the source gives the
        user an error on the field they actually edited instead of a constraint
        violation on a mirror row they never see.  A Python constraint (rather
        than a table one) is what propagates to the concrete models inheriting
        this abstract mixin.

        This constrains a field *this mixin declares*, which is the only thing
        that makes it legitimate.  The projection mixin used to carry it and so
        validated a field belonging to whichever consumer inherited it.
        """
        for record in self:
            if not 0.0 <= record.allocated_percentage <= 100.0:
                raise ValidationError(
                    self.env._(
                        "%(name)s: allocation %% must be between 0 and 100.",
                        name=record.display_name,
                    )
                )

    def _get_fields_sync_trigger(self):
        """Add the allocation share to the projection's triggers.

        It belongs here because *this mixin declares it* and every consumer
        forwards it into ``_get_reservation_vals_list``; a consumer that had to
        remember got a mirror reservation permanently stuck at the old
        percentage, and therefore a wrong ``allocated_hours``, with nothing to
        indicate it.
        """
        return super()._get_fields_sync_trigger() | {"allocated_percentage"}

    # ``reservation_ids.active`` is a dependency on purpose: ``reservation_ids``
    # drops archived rows on read (x2many active_test), so an archive flip
    # changes the aggregate without touching the relation or the summed field
    # itself — without it the stored sum goes stale.
    @api.depends("reservation_ids.allocated_hours", "reservation_ids.active")
    def _compute_allocated_hours(self):
        """Aggregate committed hours from the consumer's reservation ledger."""
        for record in self:
            record.allocated_hours = sum(
                record.reservation_ids.mapped("allocated_hours")
            )
