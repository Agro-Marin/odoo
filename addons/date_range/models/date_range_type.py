import logging

from dateutil.rrule import DAILY, MONTHLY, WEEKLY, YEARLY

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.base.models.catalog_mixin import name_uniq_index

_logger = logging.getLogger(__name__)

UNIT_SELECTION = [
    (str(YEARLY), "years"),
    (str(MONTHLY), "months"),
    (str(WEEKLY), "weeks"),
    (str(DAILY), "days"),
]


class DateRangeType(models.Model):
    """Categorizes date ranges and holds their autogeneration and naming defaults."""

    _name = "date.range.type"
    _description = "Date Range Type"
    _order = "name,id"

    name = fields.Char(required=True, translate=True)
    allow_overlap = fields.Boolean(
        default=False,
        help="If set, date ranges of this type are allowed to overlap each "
        "other. Leave unset to require them to be disjoint.",
    )
    active = fields.Boolean(
        default=True,
        help="The active field allows you to hide the date range type without removing it.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company.id,
        index=True,
    )
    date_range_ids = fields.One2many("date.range", "type_id", string="Ranges")
    date_ranges_exist = fields.Boolean(compute="_compute_date_ranges_exist")

    # Defaults for generating date ranges
    name_expr = fields.Text(
        "Range name expression",
        help=(
            "Evaluated expression. E.g. "
            "\"'FY%s' % date_start.strftime('%Y%m%d')\"\nYou can "
            "use the Date types 'date_end' and 'date_start', as well as "
            "the 'index' variable."
        ),
    )
    range_name_preview = fields.Char(compute="_compute_range_name_preview")
    name_prefix = fields.Char("Range name prefix")
    duration_count = fields.Integer("Duration")
    unit_of_time = fields.Selection(selection=UNIT_SELECTION)
    autogeneration_date_start = fields.Date(
        string="Autogeneration Start Date",
        help="Only applies when there are no date ranges of this type yet",
    )
    autogeneration_count = fields.Integer()
    autogeneration_unit = fields.Selection(selection=UNIT_SELECTION)

    _name_src_uniq = name_uniq_index(
        "company_id",
        nulls_distinct=True,
        message="A date range type must be unique per Company",
    )

    @api.constrains(
        "autogeneration_date_start",
        "autogeneration_count",
        "duration_count",
        "unit_of_time",
    )
    def _check_autogeneration_settings(self):
        """Validate that autogeneration settings are complete and positive.

        :raises ValidationError: if the start date is missing, the count or
            duration is not positive, or the unit of time is unset while
            autogeneration is configured
        """
        for record in self:
            if not record.autogeneration_count:
                continue
            if not record.autogeneration_date_start:
                raise ValidationError(
                    self.env._(
                        "Autogeneration start date is required when autogeneration count is set for type '%s'"
                    )
                    % record.name
                )
            if record.autogeneration_count < 1:
                raise ValidationError(
                    self.env._("Autogeneration count must be positive for type '%s'")
                    % record.name
                )
            if not record.duration_count or record.duration_count < 1:
                raise ValidationError(
                    self.env._(
                        "Duration count must be positive when autogeneration is enabled for type '%s'"
                    )
                    % record.name
                )
            if not record.unit_of_time:
                raise ValidationError(
                    self.env._(
                        "Unit of time must be set when autogeneration is enabled for type '%s'"
                    )
                    % record.name
                )

    @api.constrains("company_id")
    def _check_company_id(self):
        """Forbid changing the company while ranges of another company use this type.

        :raises ValidationError: if a referenced range belongs to a different company
        """
        # Bypassable via the 'bypass_company_validation' context key.
        if self.env.context.get("bypass_company_validation", False):
            return
        for rec in self.sudo():
            if not rec.company_id:
                continue
            foreign = rec.date_range_ids.filtered(
                lambda r, drt=rec: r.company_id and r.company_id != drt.company_id
            )
            if foreign:
                raise ValidationError(
                    self.env._(
                        "You cannot change the company, as this Date Range Type is assigned to Date Range '%s'."
                    )
                    % foreign[:1].display_name
                )

    @api.depends(
        "name_expr",
        "name_prefix",
        "duration_count",
        "unit_of_time",
        "autogeneration_date_start",
        "autogeneration_count",
        "autogeneration_unit",
    )
    def _compute_range_name_preview(self):
        """Preview the first name the generator would produce for this type.

        Delegated to the generator rather than reimplemented: the two used to
        disagree — the type promised ``P1`` where the wizard, and the ranges it
        actually created, said ``P01`` — because a second implementation had to
        guess how many ranges there would be. Not stored: it is a hint about
        what a future run would do, and a stored copy silently goes stale.
        """
        generator = self.env["date.range.generator"]
        for dr_type in self:
            if not (dr_type.name_expr or dr_type.name_prefix):
                dr_type.range_name_preview = False
                continue
            # count=1 is a floor, not an override: when the type configures an
            # autogeneration horizon the generator derives a real end date and
            # uses that instead, so the preview shows the padding a real run
            # would produce.
            dr_type.range_name_preview = generator.new(
                {"type_id": dr_type.id, "count": 1}
            ).range_name_preview

    @api.depends("date_range_ids")
    def _compute_date_ranges_exist(self):
        """Set whether any date range references this type."""
        for dr_type in self:
            dr_type.date_ranges_exist = bool(dr_type.date_range_ids)

    @api.onchange("name_expr")
    def onchange_name_expr(self):
        """Clear the name prefix when an expression is set, so only one applies."""
        # One-way only (prefix -> expression) to avoid wiping a hand-crafted
        # expression by accident; clearing the expression never restores the prefix.
        if self.name_expr and self.name_prefix:
            self.name_prefix = False

    def write(self, vals):
        """Cascade archiving down to the type's ranges.

        One-way on purpose. ``date.range.active`` used to be computed from this
        field, which meant restoring a type also un-archived every range someone
        had archived by hand. Ranges archived with their type stay archived
        until they are restored deliberately.
        """
        res = super().write(vals)
        if vals.get("active") is False:
            ranges = (
                self.env["date.range"]
                .with_context(active_test=False)
                .search([("type_id", "in", self.ids), ("active", "=", True)])
            )
            ranges.write({"active": False})
        return res

    @api.model
    def autogenerate_ranges(self):
        """Generate ranges for every type with complete autogeneration settings.

        Called by a scheduled action. Each type is generated in its own
        savepoint so one bad configuration cannot abort the others or poison
        the cursor for the ones that follow.
        """
        types = self.search(
            [
                ("autogeneration_count", ">", 0),
                ("autogeneration_unit", "!=", False),
                ("duration_count", ">", 0),
                ("unit_of_time", "!=", False),
            ]
        )
        for dr_type in types:
            try:
                with self.env.cr.savepoint():
                    wizard = self.env["date.range.generator"].new(
                        {"type_id": dr_type.id}
                    )
                    if not wizard.date_end:
                        # The configured horizon has not been reached yet.
                        continue
                    wizard.action_apply(batch=True)
            except Exception as error:
                _logger.warning(
                    "Error autogenerating ranges for date range type %s: %s",
                    dr_type.name,
                    error,
                )
