import logging

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import RedirectWarning, UserError
from odoo.fields import Command
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    # Many2many
    duplicated_order_ids = fields.Many2many(comodel_name="sale.order", compute="_compute_duplicated_order_ids")

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _fetch_duplicate_orders(self):
        """Fectch duplicated orders.

        :return: Dictionary mapping order to it's related duplicated orders.
        :rtype: dict
        """
        orders = self.filtered(lambda order: order.id and order.client_order_ref)
        if not orders:
            return {}

        used_fields = (
            "company_id",
            "partner_id",
            "client_order_ref",
            "origin",
            "date_order",
            "state",
        )
        self.env["sale.order"].flush_model(used_fields)

        result = self.env.execute_query(
            SQL(
                """
            SELECT
                sale_order.id AS order_id,
                array_agg(duplicate_order.id) AS duplicate_ids
              FROM sale_order
              JOIN sale_order AS duplicate_order
                ON sale_order.company_id = duplicate_order.company_id
                 AND sale_order.id != duplicate_order.id
                 AND duplicate_order.state != 'cancel'
                 AND sale_order.partner_id = duplicate_order.partner_id
                 AND sale_order.date_order = duplicate_order.date_order
                 AND sale_order.client_order_ref = duplicate_order.client_order_ref
                 AND (
                    sale_order.origin = duplicate_order.origin
                    OR (sale_order.origin IS NULL AND duplicate_order.origin IS NULL)
                )
             WHERE sale_order.id IN %(orders)s
             GROUP BY sale_order.id
            """,
                orders=tuple(orders.ids),
            )
        )
        return {order_id: set(duplicate_ids) for order_id, duplicate_ids in result}

    def _get_order_edi_decoder(self, file_data):
        """To be extended with decoding capabilities of order data from file data.

        :returns:  Function to be later used to import the file.
                   Function' args:
                   - order: sale.order
                   - file_data: attachemnt information / value
                   returns True if was able to process the order
        """
        if file_data["type"] in ("pdf", "binary"):
            return lambda *args: False
        return

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("client_order_ref", "date_order", "origin", "partner_id")
    def _compute_duplicated_order_ids(self):
        order_to_duplicate_orders = self._fetch_duplicate_orders()
        for order in self:
            order.duplicated_order_ids = [Command.set(order_to_duplicate_orders.get(order.id, []))]

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    @api.readonly
    def action_open_business_doc(self):
        self.ensure_one()
        return {
            "name": _("Order"),
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": self.id,
            "views": [(False, "form")],
        }

    # ------------------------------------------------------------
    # TOOLS
    # ------------------------------------------------------------

    def _extend_with_attachments(self, attachment):
        """Main entry point to extend/enhance order with attachment.

        :param attachment: A recordset of ir.attachment.
        :returns: None
        """
        self.ensure_one()

        file_data = attachment._unwrap_edi_attachments()[0]
        decoder = self._get_order_edi_decoder(file_data)
        if decoder:
            try:
                with self.env.cr.savepoint():
                    decoder(self, file_data)
            except RedirectWarning:
                raise
            except Exception:
                message = _(
                    "Error importing attachment '%(file_name)s' as order (decoder=%(decoder)s)",
                    file_name=file_data["filename"],
                    decoder=decoder.__name__,
                )
                self.with_user(SUPERUSER_ID).message_post(body=message)
                _logger.exception(message)

        if file_data.get("on_close"):
            file_data["on_close"]()
        return True

    @api.model
    def _create_order_from_attachment(self, attachment_ids):
        """Create the sale orders from given attachment_ids and fill data by extracting detail
        from attachments and return generated orders.

        :param list attachment_ids: List of attachments process.
        :return: Recordset of order.
        """
        attachments = self.env["ir.attachment"].browse(attachment_ids)
        if not attachments:
            raise UserError(_("No attachment was provided"))

        orders = self.browse()
        for attachment in attachments:
            order = self.create(
                {
                    "partner_id": self.env.user.partner_id.id,
                }
            )
            order._extend_with_attachments(attachment)
            orders |= order
            order.message_post(attachment_ids=attachment.ids)
            attachment.write({"res_model": self._name, "res_id": order.id})

        return orders

    def create_document_from_attachment(self, attachment_ids):
        """Create the sale orders from given attachment_ids and redirect newly create order view.

        :param list attachment_ids: List of attachments process.
        :return: An action redirecting to related sale order view.
        :rtype: dict
        """
        orders = self._create_order_from_attachment(attachment_ids)
        return orders._get_records_action(name=_("Generated Orders"))
