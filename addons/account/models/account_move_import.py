import logging
from contextlib import contextmanager

from odoo import api, models
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _get_import_source_attachment(self, selected_file_data):
        """The attachment to keep so the import can be replayed.

        An embedded file (an XML inside a PDF) has no attachment record of its
        own, so keep the file it was extracted from -- reloading unwraps it
        again.
        """
        return selected_file_data.get("attachment") or selected_file_data.get(
            "origin_attachment"
        )

    def _should_store_import_source_attachment(self, selected_file_data):
        """Hook for modules that decode a document but own the reload
        themselves; overriding this to False opts out."""
        return True

    def _set_import_source_attachment(self, file_data_group, new=False):
        self.ensure_one()
        selected_file_data = self._get_selected_import_file_data(
            file_data_group, new=new
        )
        if self._should_store_import_source_attachment(selected_file_data):
            self.import_source_attachment_id = self._get_import_source_attachment(
                selected_file_data
            )

    def _reset_fields_for_reload(self):
        """Clear what the import fills in, so reloading restores rather than
        merges. Anything the user owns outright -- the journal, the company --
        is left alone."""
        with self._get_edi_creation() as move_form:
            move_form.partner_id = False
            move_form.invoice_date = False
            move_form.invoice_payment_term_id = False
            move_form.invoice_date_due = False

            if move_form.is_purchase_document(include_receipts=True):
                move_form.ref = False
            elif (
                move_form.is_sale_document(include_receipts=True)
                and move_form.quick_edit_mode
            ):
                move_form.name = False

            move_form.payment_reference = False
            move_form.currency_id = move_form.company_currency_id
            move_form.invoice_line_ids = [Command.clear()]

    def action_reload_imported_data(self):
        """Decode the source file again, discarding edits made since."""
        self.ensure_one()
        record = self.with_context(skip_is_manually_modified=True)
        try:
            record._reset_fields_for_reload()

            files_data = record._to_files_data(record.import_source_attachment_id)
            files_data.extend(record._unwrap_attachments(files_data))
            file_data_groups = record._group_files_data_into_groups_of_mixed_types(
                files_data
            )
            record._extend_with_attachments(file_data_groups[0])
        except Exception as e:
            _logger.warning(
                "Error while reloading imported data on account.move %d: %s", self.id, e
            )
            raise UserError(self.env._("Couldn't reload data.")) from e

    def _extend_with_attachments(self, files_data, new=False):
        existing_lines = self.invoice_line_ids
        res = super()._extend_with_attachments(files_data, new)

        if res:
            self._set_import_source_attachment(files_data, new=new)

        if new_lines := (self.invoice_line_ids - existing_lines):
            new_lines.is_imported = True
            if not existing_lines:
                try:
                    self.with_context(
                        default_move_type=self.move_type
                    )._link_bill_origin_to_purchase_orders(timeout=4)
                except UserError, ValueError:
                    _logger.exception("Failed to link bill to purchase order")

        if new and res:
            self._portal_ensure_token()
            self.flush_recordset(["access_token"])
            try:
                attachments = set(
                    self.attachment_ids
                    + self._from_files_data(
                        files_data + self._unwrap_attachments(files_data)
                    )
                )
                self.journal_id._notify_invoice_subscribers(
                    invoice=self,
                    mail_params={
                        "attachment_ids": [
                            Command.create(
                                {
                                    "name": f"MAIL_{attachment['name']}",
                                    "mimetype": attachment["mimetype"],
                                    "raw": attachment["raw"],
                                }
                            )
                            for attachment in attachments
                        ]
                    },
                )
            except Exception:
                _logger.exception(
                    "Failed to notify invoice subscribers after EDI import."
                )

        self._post_process_link_to_purchase_order(self)

        return res

    @contextmanager
    def _get_edi_creation(self):
        container = {"records": self}
        with (
            self._check_balanced(container),
            self._disable_discount_precision(),
            self._sync_dynamic_lines(container),
        ):
            move = self or self.create({})
            container["records"] = move
            yield move

    @contextmanager
    def _disable_discount_precision(self):
        with self._disable_recursion("ignore_discount_precision"):
            yield

    def _reason_cannot_decode_has_invoice_lines(self):
        if self.invoice_line_ids:
            return self.env._("The invoice already contains lines.")
        return None

    @api.model
    def _post_process_link_to_purchase_order(self, invoice):
        pass

    def _prepare_edi_vals_to_export(self):
        self.ensure_one()

        res = {
            "record": self,
            "balance_multiplicator": -1 if self.is_inbound() else 1,
            "invoice_line_vals_list": [],
        }

        for index, line in enumerate(
            self.invoice_line_ids.filtered(lambda line: line.display_type == "product"),
            start=1,
        ):
            line_vals = line._prepare_edi_vals_to_export()
            line_vals["index"] = index
            res["invoice_line_vals_list"].append(line_vals)

        res.update(
            {
                "total_price_subtotal_before_discount": sum(
                    x["price_subtotal_before_discount"]
                    for x in res["invoice_line_vals_list"]
                ),
                "total_price_discount": sum(
                    x["price_discount"] for x in res["invoice_line_vals_list"]
                ),
            }
        )

        return res
