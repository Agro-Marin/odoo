from odoo import fields, models
from odoo.fields import Command


class AccountMoveLine(models.Model):
    """Invoice-line helpers shared by the order types.

    sale and purchase each link an invoice line back to the order lines that
    produced it, and each hangs the product's internal warning off it. Neither
    is order-type specific beyond the field names, so the bodies live here and
    the concrete modules only register their link field.
    """

    _inherit = "account.move.line"

    # FIELDS

    # Shared by sale and purchase invoice lines; declared here so the generic
    # ``order.line.invoice.mixin._prepare_aml_vals`` can set it without either
    # module installed.
    is_downpayment = fields.Boolean()

    # ------------------------------------------------------------
    # ORDER LINE LINKS
    # ------------------------------------------------------------

    def _get_order_line_link_fields(self):
        """Many2many fields linking this invoice line back to its order lines.

        Each order module appends its own (``sale_line_ids``,
        ``purchase_line_ids``), so a deployment with only one of them installed
        sees only that one. Registering here is what lets the two methods below
        be written once instead of once per module.

        :rtype: list[str]
        """
        return []

    def _copy_data_extend_business_fields(self, values):
        """Carry the order-line links onto the copy.

        Without this a duplicated invoice line loses its link to the order, and
        the order's invoiced quantities stop adding up.
        """
        super()._copy_data_extend_business_fields(values)
        for field_name in self._get_order_line_link_fields():
            values[field_name] = [Command.set(self[field_name].ids)]

    def _related_analytic_distribution(self):
        """Inherit the analytic distribution from the originating order line.

        Only the first linked line is consulted, matching what sale and
        purchase each did on their own: an invoice line aggregating several
        order lines has no single distribution to inherit, and guessing between
        them would be worse than taking the one the line came from.
        """
        vals = super()._related_analytic_distribution()
        for field_name in self._get_order_line_link_fields():
            if order_lines := self[field_name]:
                vals |= order_lines[0].analytic_distribution or {}
        return vals

    # ------------------------------------------------------------
    # PRODUCT WARNINGS
    # ------------------------------------------------------------

    def _compute_warn_msg_from_product(self, field_name, group):
        """Copy the product's internal warning into ``field_name``.

        The invoice-line field and the ``product.product`` field share a name on
        both order types, so one name covers the read and the write. Concrete
        models keep their own field because the ``@api.depends`` has to name the
        product field it reads; only the body is shared — the same split as
        ``order.line.fields.mixin._compute_line_warn_msg``.

        :param str field_name: Text field to fill, named as on ``product.product``
        :param str group: group the user must hold to see warnings at all
        """
        has_warning_group = self.env.user.has_group(group)
        for line in self:
            line[field_name] = line.product_id[field_name] if has_warning_group else ""
