# Part of Odoo. See LICENSE file for full copyright and licensing details.


from datetime import timedelta
from typing import Literal, Self

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.libs.numbers.float_utils import RoundingMethod
from odoo.tools import float_compare, float_is_zero, float_round


class UomUom(models.Model):
    _name = 'uom.uom'
    _description = 'Product Unit of Measure'
    _parent_name = 'relative_uom_id'
    _parent_store = True
    _order = 'sequence, relative_uom_id, id'

    name = fields.Char('Unit Name', required=True, translate=True)
    sequence = fields.Integer(compute="_compute_sequence", store=True, readonly=False, precompute=True)
    relative_factor = fields.Float(
        'Contains',
        default=1.0,
        digits=0,  # falsy digits force NUMERIC with unlimited precision
        required=True,
        help='How much bigger or smaller this unit is compared to the reference UoM for this unit',
    )
    rounding = fields.Float('Rounding Precision', compute="_compute_rounding")
    active = fields.Boolean(
        'Active', default=True, help="Uncheck the active field to disable a unit of measure without deleting it."
    )
    relative_uom_id = fields.Many2one('uom.uom', 'Reference Unit', ondelete='cascade', index='btree_not_null')
    related_uom_ids = fields.One2many('uom.uom', 'relative_uom_id', 'Related UoMs')
    factor = fields.Float('Absolute Quantity', digits=0, compute='_compute_factor', recursive=True, store=True)
    parent_path = fields.Char(index=True)

    _factor_gt_zero = models.Constraint(
        'CHECK (relative_factor > 0)',
        'The conversion ratio for a unit of measure must be strictly positive!',
    )

    # === COMPUTE METHODS === #

    @api.depends('relative_factor')
    def _compute_sequence(self):
        for uom in self:
            if uom.id and uom.sequence:
                # Only set a default sequence before the record creation, or on module update if
                # there is no value.
                continue
            uom.sequence = min(int(uom.relative_factor * 100.0), 1000)

    def _compute_rounding(self):
        """All Units of Measure share the same rounding precision defined in 'Product Unit'.
        Set in a compute to ensure compatibility with previous calls to `uom.rounding`.
        """
        decimal_precision = self.env['decimal.precision'].precision_get('Product Unit')
        self.rounding = 10**-decimal_precision

    @api.depends('relative_factor', 'relative_uom_id', 'relative_uom_id.factor')
    def _compute_factor(self):
        for uom in self:
            if uom.relative_uom_id:
                uom.factor = uom.relative_factor * uom.relative_uom_id.factor
            else:
                uom.factor = uom.relative_factor

    # === ONCHANGE METHODS === #

    @api.onchange('relative_factor', 'relative_uom_id')
    def _onchange_critical_fields(self):
        if self._filter_protected_uoms() and self.create_date < (fields.Datetime.now() - timedelta(days=1)):
            return {
                'warning': {
                    'title': _("Warning for %s", self.name),
                    'message': _(
                        "Some critical fields have been modified on %s.\n"
                        "Note that existing data WON'T be updated by this change.\n\n"
                        "As units of measure impact the whole system, this may cause critical issues.\n"
                        "Therefore, changing core units of measure in a running database is not recommended.",
                        self.name,
                    ),
                }
            }
        return None

    # === CONSTRAINT METHODS === #

    @api.constrains('relative_factor', 'relative_uom_id')
    def _check_factor(self):
        for uom in self:
            if not uom.relative_uom_id and float_compare(uom.relative_factor, 1.0, precision_digits=12) != 0:
                raise UserError(_(
                    "The unit of measure %s has a conversion ratio but no reference unit."
                    " Either set a reference unit or keep a ratio of 1.",
                    uom.display_name,
                ))

    # === CRUD METHODS === #

    @api.ondelete(at_uninstall=False)
    def _unlink_except_master_data(self):
        locked_uoms = self._filter_protected_uoms()
        if locked_uoms:
            raise UserError(
                _(
                    "The following units of measure are used by the system and cannot be deleted: %s\nYou can archive them instead.",
                    ", ".join(locked_uoms.mapped('name')),
                )
            )

    # === BUSINESS METHODS === #

    def round(self, value: float, rounding_method: RoundingMethod = 'HALF-UP') -> float:
        """Round the value using the 'Product Unit' precision"""
        self.ensure_one()
        digits = self.env['decimal.precision'].precision_get('Product Unit')
        return float_round(value, precision_digits=digits, rounding_method=rounding_method)

    def compare(self, value1: float, value2: float) -> Literal[-1, 0, 1]:
        """Compare two measures after rounding them with the 'Product Unit' precision

        :param value1: origin value to compare
        :param value2: value to compare to
        :return: -1, 0 or 1, if ``value1`` is lower than, equal to, or greater than ``value2``.
        """
        self.ensure_one()
        digits = self.env['decimal.precision'].precision_get('Product Unit')
        return float_compare(value1, value2, precision_digits=digits)

    def is_zero(self, value: float) -> bool:
        """Check if the value is zero after rounding with the 'Product Unit' precision"""
        self.ensure_one()
        digits = self.env['decimal.precision'].precision_get('Product Unit')
        return float_is_zero(value, precision_digits=digits)

    @api.depends('name', 'relative_factor', 'relative_uom_id')
    @api.depends_context('formatted_display_name')
    def _compute_display_name(self):
        super()._compute_display_name()
        for uom in self:
            if uom.env.context.get('formatted_display_name') and uom.relative_uom_id:
                uom.display_name = f"{uom.name}\t--{uom.relative_factor} {uom.relative_uom_id.name}--"

    def _compute_quantity(
        self,
        qty: float,
        to_unit: Self,
        round: bool = True,
        rounding_method: RoundingMethod = 'UP',
        raise_if_failure: bool = True,
    ) -> float:
        """Convert the given quantity from the current UoM `self` into a given one

        :param qty: the quantity to convert
        :param to_unit: the destination UomUom record (uom.uom)
        :param raise_if_failure: behavior when the conversion is not possible
            (`self` and `to_unit` have no common reference unit):
            - if true, raise a UserError,
            - otherwise, return the initial quantity unconverted

        Call-sites that must degrade instead of raising use the named
        wrappers below (`_compute_quantity_report` / `_compute_quantity_estimate`
        / `_compute_quantity_reconcile`) — see the comment block above them
        for the decision rule.
        """
        if not self or not qty:
            return qty
        self.ensure_one()

        if self == to_unit:
            amount = qty
        else:
            if to_unit and not self._has_common_reference(to_unit):
                if raise_if_failure:
                    raise UserError(_(
                        "The unit of measure %(unit)s cannot be converted into %(other_unit)s"
                        " because they do not share a common reference unit.",
                        unit=self.name,
                        other_unit=to_unit.name,
                    ))
                return qty
            amount = qty * self.factor
            if to_unit:
                amount = amount / to_unit.factor

        if to_unit and round:
            amount = float_round(amount, precision_rounding=to_unit.rounding, rounding_method=rounding_method)

        return amount

    # --- Degrade-on-failure wrappers ------------------------------------
    # `_compute_quantity` raises when the units share no common reference.
    # Call-sites that must degrade instead (return the quantity unconverted,
    # visibly wrong but non-blocking) use one of the named wrappers below so
    # the intent stays greppable per bucket. Pick by what the value feeds:
    # - _compute_quantity_report: a screen, PDF or aggregate display.
    # - _compute_quantity_estimate: a forecast/planning/pricing estimate
    #   that guides but does not size a record.
    # - _compute_quantity_reconcile: a stored reconciliation compute
    #   (qty_transferred/qty_invoiced family) matching moves or invoice
    #   lines back to order lines; not a financial posting.
    # Anything that creates or sizes a real record (moves, MOs, order or
    # invoice lines, valuation/COGS) stays on the strict base method. The
    # opt-out is forced: a caller-passed `raise_if_failure` is discarded.

    def _compute_quantity_lenient(self, qty: float, to_unit: Self, **kwargs) -> float:
        """Shared body of the degrade wrappers; call those, not this."""
        kwargs.pop('raise_if_failure', None)
        return self._compute_quantity(qty, to_unit, raise_if_failure=False, **kwargs)

    def _compute_quantity_report(self, qty: float, to_unit: Self, **kwargs) -> float:
        """Convert for a display/report value; degrades on incompatible units."""
        return self._compute_quantity_lenient(qty, to_unit, **kwargs)

    def _compute_quantity_estimate(self, qty: float, to_unit: Self, **kwargs) -> float:
        """Convert for a planning/pricing estimate; degrades on incompatible units."""
        return self._compute_quantity_lenient(qty, to_unit, **kwargs)

    def _compute_quantity_reconcile(self, qty: float, to_unit: Self, **kwargs) -> float:
        """Convert for a stored reconciliation compute; degrades on incompatible units."""
        return self._compute_quantity_lenient(qty, to_unit, **kwargs)

    def _check_qty(self, product_qty, uom, rounding_method="HALF-UP"):
        """Round `product_qty` (expressed in `uom`) to a whole multiple of the
        packaging `self`, according to `rounding_method` ("UP", "HALF-UP" or "DOWN").
        """
        self.ensure_one()
        if self == uom:
            return product_qty
        # One package expressed in `uom`, unrounded: rounding it first would
        # distort the multiples (e.g. a Unit is 1/12 Dozen, not 0.08).
        packaging_qty = self._compute_quantity(1, uom, round=False)
        # We do not use the modulo operator to check if qty is a multiple of q. Indeed the quantity
        # per package might be a float, leading to incorrect results. For example:
        # 8 % 1.6 = 1.5999999999999996
        # 5.4 % 1.8 = 2.220446049250313e-16
        if product_qty and packaging_qty:
            product_qty = (
                float_round(product_qty / packaging_qty, precision_rounding=1.0, rounding_method=rounding_method)
                * packaging_qty
            )
            # The whole-package count is already fixed; this only strips float
            # artefacts (e.g. 144 * 1/12 = 12.000000000000002).
            product_qty = float_round(product_qty, precision_rounding=uom.rounding, rounding_method='HALF-UP')
        return product_qty

    def _compute_price(self, price: float, to_unit: Self) -> float:
        """Convert a price per unit of `self` into a price per unit of `to_unit`."""
        self.ensure_one()
        if not price or not to_unit or self == to_unit:
            return price
        return price * to_unit.factor / self.factor

    def _unprotected_uom_xml_ids(self):
        """Return a list of UoM XML IDs that are not protected by default.
        Note: Some of these may be protected via overrides in other modules.
        """
        return [
            "product_uom_hour",
            "product_uom_dozen",
            "product_uom_pack_6",
        ]

    def _filter_protected_uoms(self):
        """Return the subset of `self` that is protected master data."""
        linked_model_data = (
            self.env['ir.model.data']
            .sudo()
            .search(
                [
                    ('model', '=', self._name),
                    ('res_id', 'in', self.ids),
                    ('module', '=', 'uom'),
                    ('name', 'not in', self._unprotected_uom_xml_ids()),
                ]
            )
        )
        return self.browse(set(linked_model_data.mapped('res_id')))

    def _get_reference_uom(self) -> Self:
        """Return the root unit `self` is (transitively) defined against."""
        self.ensure_one()
        uom = self
        while uom.relative_uom_id:
            uom = uom.relative_uom_id
        return uom

    def _has_common_reference(self, other_uom: Self) -> bool:
        """Check if `self` and `other_uom` have a common reference unit"""
        self.ensure_one()
        other_uom.ensure_one()
        if self.parent_path and other_uom.parent_path:
            return self.parent_path.split('/', 1)[0] == other_uom.parent_path.split('/', 1)[0]
        # New records (e.g. during an onchange) have no parent_path yet.
        return self._get_reference_uom() == other_uom._get_reference_uom()
