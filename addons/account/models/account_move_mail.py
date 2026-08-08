"""mail.thread integration for account.move."""

# An invoice is a mail.thread: it is created from an incoming email, it notifies
# a customer, and its chatter carries the audit trail. This is the model's half
# of that contract -- routing, message hooks, recipient groups and the rendering
# context for the notification email. Extracted from account_move.py.

from markupsafe import Markup

from odoo import _, api, models
from odoo.fields import Command
from odoo.tools import format_amount, format_date
from odoo.tools.mail import email_re, email_split, generate_tracking_message_id


class AccountMove(models.Model):
    _inherit = "account.move"

    def _mailing_get_default_domain(self, mailing):
        return ["&", ("move_type", "=", "out_invoice"), ("state", "=", "posted")]

    @api.model
    def _routing_check_route(self, message, message_dict, route, raise_exception=True):
        if route[0] == "account.move" and len(message_dict["attachments"]) < 1:
            # Don't create the move if no attachment.
            company_id = route[2].get("company_id", self.env.company.id)
            if not isinstance(company_id, int):
                raise ValueError(
                    _(
                        "Default value for 'company_id' for %(record)s is not an integer",
                        record=route[4],
                    )
                )
            journal_alias_company = self.env["res.company"].search(
                [["id", "=", company_id]]
            )
            body = self.env["ir.qweb"]._render(
                "account.email_template_mail_gateway_failed",
                {
                    "company_email": journal_alias_company.email
                    or self.env.company.email,
                    "company_name": journal_alias_company.name or self.env.company.name,
                },
            )
            # Send as the journal alias' company, not as whatever company the
            # gateway user happens to be in: `_routing_create_bounce_email`
            # derives the sender from `self.env.company.bounce_email`, so
            # without this a bounce for company B goes out from company A.
            reply_to_journal_company = (
                journal_alias_company.email or self.env.company.email
            )
            self.with_company(journal_alias_company)._routing_create_bounce_email(
                message_dict["from"],
                body,
                message,
                references=f"{message_dict['message_id']} {generate_tracking_message_id('loop-detection-bounce-email')}",
                reply_to=reply_to_journal_company,
            )
            return ()
        return super()._routing_check_route(
            message, message_dict, route, raise_exception=raise_exception
        )

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        # EXTENDS mail mail.thread
        custom_values = custom_values or {}
        # Add custom behavior when receiving a new invoice through the mail's gateway.
        if custom_values.get("move_type", "entry") not in (
            "out_invoice",
            "in_invoice",
            "entry",
        ):
            return super().message_new(msg_dict, custom_values=custom_values)

        self = self.with_context(skip_is_manually_modified=True)

        company = (
            self.env["res.company"].browse(custom_values["company_id"])
            if custom_values.get("company_id")
            else self.env.company
        )

        def is_internal_partner(partner):
            # Helper to know if the partner is an internal one.
            return company.partner_id in (partner | partner.parent_id) or (
                partner.user_ids
                and all(user._is_internal() for user in partner.user_ids)
            )

        def filter_found(partner):
            return (
                not company
                or partner.company_id.id in [False, company.id]
                or partner.partner_share
            )

        # Search for partner that sent the mail.
        from_mail_addresses = email_split(msg_dict.get("from", ""))
        partners = self._partner_find_from_emails_single(
            from_mail_addresses, filter_found=filter_found, no_create=True
        )
        # if we are in the case when an internal user forwarded the mail manually
        # search for partners in mail's body
        if (
            partners
            and is_internal_partner(partners[0])
            and (
                body_mail_addresses := set(email_re.findall(msg_dict.get("body") or ""))
            )
        ):
            # Search for partners in the mail's body.
            partners = self._partner_find_from_emails_single(
                body_mail_addresses, filter_found=filter_found, no_create=True
            )

        # Never return an internal partner
        partners = partners.filtered(lambda p: not is_internal_partner(p))

        # Little hack: Inject the mail's subject in the body.
        if msg_dict.get("subject") and msg_dict.get("body"):
            msg_dict["body"] = Markup("<div><div><h3>%s</h3></div>%s</div>") % (
                msg_dict["subject"],
                msg_dict["body"],
            )

        # Create the invoice.
        values = {
            "name": "/",  # we have to give the name otherwise it will be set to the mail's subject
            # A gateway mail can have a missing/unparseable From: bounce
            # gracefully instead of crashing invoice creation.
            "invoice_source_email": (
                from_mail_addresses[0] if from_mail_addresses else False
            ),
            "partner_id": partners[0].id if partners else False,
        }
        move_ctx = self.with_context(
            from_alias=True,
            default_move_type=custom_values.get("move_type", "entry"),
            default_journal_id=custom_values.get("journal_id"),
            default_company_id=company.id,
        )
        move = super(AccountMove, move_ctx).message_new(msg_dict, custom_values=values)
        move._compute_name()  # because the name is given, we need to recompute in case it is the first invoice of the journal

        return move

    def _attachment_fields_to_clear(self):
        return super()._attachment_fields_to_clear() + ["message_main_attachment_id"]

    def _message_post_after_hook(self, new_message, message_values):
        """This method processes the attachments of a new mail.message. It handles the 3 following situations:
        (1) receiving an e-mail from a mail alias. In that case, we potentially want to split the attachments into several invoices.
        (2) receiving an e-mail / posting a message on an existing invoice via the webclient:
            (2)(a): If the poster is an internal user, we enhance the invoice with the attachments.
            (2)(b): Otherwise, we don't do any further processing.
        (3) posting a message on an invoice in application code. In that case, don't do anything.

        Furthermore, in cases (1) and (2), we decide for each attachment whether to add it as an attachment on the invoice,
        based on its mimetype.
        """
        # EXTENDS mail mail.thread
        attachments = new_message.attachment_ids

        if (
            not attachments
            or new_message.message_type not in {"email", "comment"}
            or self.env.context.get("disable_attachment_import")
        ):
            # No attachments, or the message was created in application code, so don't do anything.
            return super()._message_post_after_hook(new_message, message_values)

        files_data = self._to_files_data(attachments)

        # Extract embedded files. Note that `_unwrap_attachments` may create ir.attachment records - for example
        # see l10n_{es,it}_edi, so to retrieve those attachments you should use the `_from_files_data` method.
        files_data.extend(self._unwrap_attachments(files_data))

        # Dispatch the attachments into groups, and create a new invoice for each group beyond the first.
        valid_files_data = []
        extra_files_data = []
        for file_data in files_data:
            if (
                self._should_attach_to_record(file_data["attachment"])
                or file_data["xml_tree"] is not None
            ):
                valid_files_data.append(file_data)
            else:
                extra_files_data.append(file_data)

        if self.env.context.get("from_alias"):
            # This is a newly-created invoice from a mail alias.
            file_data_groups = self._group_files_data_into_groups_of_mixed_types(
                valid_files_data
            ) or [[]]
            invoices = self
            if len(file_data_groups) > 1:
                # One fresh vals dict per record: `n * [dict]` aliases the
                # same dict n times, so any create override mutating its vals
                # in place would corrupt the sibling records' values.
                create_vals = [
                    self.copy_data()[0].copy()
                    for _unused in range(len(file_data_groups) - 1)
                ]
                invoices |= self.with_context(skip_is_manually_modified=True).create(
                    create_vals
                )

            for invoice, file_data_group in zip(
                invoices, file_data_groups, strict=False
            ):
                attachment_records = self._from_files_data(file_data_group)
                if invoice == self:
                    attachment_records |= self._from_files_data(extra_files_data)
                    new_message.attachment_ids = [Command.set(attachment_records.ids)]
                    message_values["attachment_ids"] = [
                        Command.link(attachment.id) for attachment in attachment_records
                    ]
                    res = super(
                        AccountMove, self.with_context(no_document=True)
                    )._message_post_after_hook(new_message, message_values)
                else:
                    sub_new_message = new_message.copy(
                        {
                            "res_id": invoice.id,
                            "attachment_ids": [Command.set(attachment_records.ids)],
                        }
                    )
                    sub_message_values = {
                        **message_values,
                        "res_id": invoice.id,
                        "attachment_ids": [
                            Command.link(attachment.id)
                            for attachment in attachment_records
                        ],
                    }
                    super(
                        AccountMove, invoice.with_context(no_document=True)
                    )._message_post_after_hook(sub_new_message, sub_message_values)
                invoice._fix_attachments_on_record_from_files_data(
                    file_data_group, extra_files_data
                )

            for invoice, file_data_group in zip(
                invoices, file_data_groups, strict=False
            ):
                if file_data_group:
                    invoice._extend_with_attachments(file_data_group, new=True)

            return res

        else:
            # This is an existing invoice on which a message was posted either by e-mail or via the webclient.
            attachment_records = self._from_files_data(files_data)
            self._fix_attachments_on_record_from_files_data(
                valid_files_data, extra_files_data
            )

            # Only trigger decoding if the message was sent by an active internal user (note OdooBot is always inactive).
            if self.env.user.active and self.env.user._is_internal():
                self._extend_with_attachments(files_data)

            new_message.attachment_ids = [Command.set(attachment_records.ids)]
            message_values["attachment_ids"] = [
                Command.link(attachment.id) for attachment in attachment_records
            ]
            return super()._message_post_after_hook(new_message, message_values)

    def _creation_subtype(self):
        # EXTENDS mail mail.thread
        if self.move_type in ("out_invoice", "out_receipt"):
            return self.env.ref("account.mt_invoice_created")
        else:
            return super()._creation_subtype()

    def _track_subtype(self, init_values):
        # EXTENDS mail mail.thread
        # add custom subtype depending of the state.
        self.ensure_one()

        if not self.is_invoice(include_receipts=True):
            if self.origin_payment_id and "state" in init_values:
                self.origin_payment_id._message_track(
                    ["state"], {self.origin_payment_id.id: init_values}
                )
            return super()._track_subtype(init_values)

        if "payment_state" in init_values and self.payment_state == "paid":
            return self.env.ref("account.mt_invoice_paid")
        elif (
            "state" in init_values
            and self.state == "posted"
            and self.is_sale_document(include_receipts=True)
        ):
            return self.env.ref("account.mt_invoice_validated")
        return super()._track_subtype(init_values)

    def _creation_message(self):
        # EXTENDS mail mail.thread
        if not self.is_invoice(include_receipts=True):
            return super()._creation_message()
        return {
            "out_invoice": _("Invoice Created"),
            "out_refund": _("Credit Note Created"),
            "in_invoice": _("Vendor Bill Created"),
            "in_refund": _("Refund Created"),
            "out_receipt": _("Sales Receipt Created"),
            "in_receipt": _("Purchase Receipt Created"),
        }[self.move_type]

    def _notify_by_email_prepare_rendering_context(
        self,
        message,
        msg_vals=False,
        model_description=False,
        force_email_company=False,
        force_email_lang=False,
        force_record_name=False,
    ):
        # EXTENDS mail mail.thread
        render_context = super()._notify_by_email_prepare_rendering_context(
            message,
            msg_vals=msg_vals,
            model_description=model_description,
            force_email_company=force_email_company,
            force_email_lang=force_email_lang,
            force_record_name=force_record_name,
        )
        record = render_context["record"]
        subtitles = [
            f"{record.display_name} - {record.partner_id.name}"
            if record.partner_id.name
            else record.display_name
        ]
        if self.is_invoice(include_receipts=True):
            # Only show the amount in emails for non-miscellaneous moves. It might confuse recipients otherwise.
            if self.invoice_date_due and self.payment_state not in (
                "in_payment",
                "paid",
            ):
                subtitles.append(
                    _(
                        "%(amount)s due\N{NO-BREAK SPACE}%(date)s",
                        amount=format_amount(
                            self.env,
                            self.amount_total
                            or self.tax_totals.get("total_amount_currency", 0),
                            self.currency_id,
                            lang_code=render_context.get("lang"),
                        ),
                        date=format_date(
                            self.env,
                            self.invoice_date_due,
                            lang_code=render_context.get("lang"),
                        ),
                    )
                )
            else:
                subtitles.append(
                    format_amount(
                        self.env,
                        self.amount_total
                        or self.tax_totals.get("total_amount_currency", 0),
                        self.currency_id,
                        lang_code=render_context.get("lang"),
                    )
                )
        render_context["subtitles"] = subtitles
        return render_context

    def _get_mail_thread_data_attachments(self):
        res = super()._get_mail_thread_data_attachments()
        # else, attachments with 'res_field' get excluded
        return res | self.env["account.move.send"]._get_invoice_extra_attachments(self)
