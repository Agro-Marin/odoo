"""``account.move`` EDI / incoming-document helpers.

This is an ``_inherit`` split of :class:`~odoo.addons.account.models.account_move.AccountMove`
extracted from ``account_move.py`` to keep the EDI concern (importing/decoding
incoming vendor documents and preparing values for export) in one place.

Note: this file belongs to the ``account`` addon and is unrelated to the
separate ``account_edi`` addon (which provides its own ``account.edi.*`` models);
it only groups methods that already lived on ``account.move``.
"""

import logging
from contextlib import contextmanager

from odoo import api, models
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    def _extend_with_attachments(self, files_data, new=False):
        existing_lines = self.invoice_line_ids
        res = super()._extend_with_attachments(files_data, new)

        if new_lines := (self.invoice_line_ids - existing_lines):
            new_lines.is_imported = True
            if not existing_lines:
                try:
                    self.with_context(
                        default_move_type=self.move_type
                    )._link_bill_origin_to_purchase_orders(timeout=4)
                except UserError, ValueError:
                    _logger.exception("Failed to link bill to purchase order")

        if new:
            # we force an early access token write to prevent edge-cases where the notification
            # email will fail because the OCR/IAP (async) callback triggers a concurrent update on the same
            # account move
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
        """Get an environment to import documents from other sources."""
        container = {"records": self}
        # Defer dynamic-line computation to the end of the block instead of
        # recomputing on every invoice line added.
        with (
            self._check_balanced(container),
            self._disable_discount_precision(),
            self._sync_dynamic_lines(container),
        ):
            # Edit the current move, or create a new one on an empty recordset.
            move = self or self.create({})
            # Register the created move before yield: if the body raises, the
            # guards' cleanup still needs to know which record they wrapped.
            container["records"] = move
            yield move

    @contextmanager
    def _disable_discount_precision(self):
        """Disable the user-defined precision for discounts."""
        # A discount on a document imported from other software/providers must
        # keep its original value rather than be rounded to the local settings.
        with self._disable_recursion({"records": self}, "ignore_discount_precision"):
            yield

    def _reason_cannot_decode_has_invoice_lines(self):
        """Helper to get a reason why an invoice cannot be decoded if it has invoice lines."""
        if self.invoice_line_ids:
            return self.env._("The invoice already contains lines.")
        return None

    @api.model
    def _post_process_link_to_purchase_order(self, invoice):
        # To be implemented in modules needing to process the invoice after it was linked (or not) to a PO
        pass

    def _prepare_edi_vals_to_export(self):
        """Prepare values to export an invoice through the EDI system.

        :return: pre-processed values for the EDI export
        :rtype: dict
        """
        self.ensure_one()

        res = {
            "record": self,
            "balance_multiplicator": -1 if self.is_inbound() else 1,
            "invoice_line_vals_list": [],
        }

        # Per-line values, including the tax details whose base-amount
        # computation is handled by the line-level helper.
        for index, line in enumerate(
            self.invoice_line_ids.filtered(lambda line: line.display_type == "product"),
            start=1,
        ):
            line_vals = line._prepare_edi_vals_to_export()
            line_vals["index"] = index
            res["invoice_line_vals_list"].append(line_vals)

        # Totals.
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
