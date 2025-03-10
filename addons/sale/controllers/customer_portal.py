import binascii

from odoo import fields, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.orm.utils import SUPERUSER_ID
from odoo.tools.translate import _

from odoo.addons.payment.controllers import portal as payment_portal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class CustomerPortal(payment_portal.PaymentPortal):
    """Extends the customer portal to provide sales order and quotation management functionalities.

    This module enables customers to view, accept, and decline quotations, as well as manage their
    orders and payments through the portal. It also supports document downloads and payment processing
    for sales orders."""

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        SaleOrder = request.env["sale.order"]
        if "count_quotation" in counters:
            values["count_quotation"] = (
                SaleOrder.search_count(self._prepare_quotations_domain(partner))
                if SaleOrder.has_access("read")
                else 0
            )
        if "order_count" in counters:
            values["order_count"] = (
                SaleOrder.search_count(self._prepare_orders_domain(partner), limit=1)
                if SaleOrder.has_access("read")
                else 0
            )

        return values

    def _prepare_quotations_domain(self, partner):
        return [
            ("message_partner_ids", "child_of", [partner.commercial_partner_id.id]),
            ("state", "=", "sent"),
        ]

    def _prepare_orders_domain(self, partner):
        return [
            ("message_partner_ids", "child_of", [partner.commercial_partner_id.id]),
            ("state", "=", "sale"),
        ]

    def _get_sale_searchbar_sortings(self):
        return {
            "date": {"label": _("Order Date"), "order": "date_order desc"},
        }

    def _prepare_sale_portal_rendering_values(
        self,
        page=1,
        date_begin=None,
        date_end=None,
        sortby=None,
        quotation_page=False,
        **kwargs,
    ):
        SaleOrder = request.env["sale.order"]

        if not sortby:
            sortby = "date"

        partner = request.env.user.partner_id
        values = self._prepare_portal_layout_values()

        if quotation_page:
            url = "/my/quotes"
            domain = self._prepare_quotations_domain(partner)
        else:
            url = "/my/orders"
            domain = self._prepare_orders_domain(partner)

        searchbar_sortings = self._get_sale_searchbar_sortings()

        sort_order = searchbar_sortings[sortby]["order"]

        if date_begin and date_end:
            domain += [
                ("create_date", ">", date_begin),
                ("create_date", "<=", date_end),
            ]

        url_args = {"date_begin": date_begin, "date_end": date_end}

        if len(searchbar_sortings) > 1:
            url_args["sortby"] = sortby

        pager_values = portal_pager(
            url=url,
            total=SaleOrder.search_count(domain),
            page=page,
            step=self._items_per_page,
            url_args=url_args,
        )
        orders = SaleOrder.search(
            domain,
            order=sort_order,
            limit=self._items_per_page,
            offset=pager_values["offset"],
        )

        values.update(
            {
                "date": date_begin,
                "quotations": orders.sudo() if quotation_page else SaleOrder,
                "orders": orders.sudo() if not quotation_page else SaleOrder,
                "page_name": "quote" if quotation_page else "order",
                "pager": pager_values,
                "default_url": url,
            }
        )

        if len(searchbar_sortings) > 1:
            values.update(
                {
                    "sortby": sortby,
                    "searchbar_sortings": searchbar_sortings,
                }
            )

        return values

    def _get_payment_values(self, order_sudo, downpayment=False, **kwargs):
        """Return the payment-specific QWeb context values.

        :param sale.order order_sudo: The sales order being paid.
        :param bool downpayment: Whether the current payment is a downpayment.
        :param dict kwargs: Locally unused data passed to `_get_compatible_providers` and
                            `_get_available_tokens`.
        :return: The payment-specific values.
        :rtype: dict
        """
        logged_in = not request.env.user._is_public()
        partner_sudo = (
            request.env.user.partner_id if logged_in else order_sudo.partner_id
        )
        company = order_sudo.company_id
        if downpayment:
            amount = order_sudo._get_prepayment_required_amount()
        else:
            amount = order_sudo.amount_total - order_sudo.amount_paid
        currency = order_sudo.currency_id

        availability_report = {}
        # Select all the payment methods and tokens that match the payment context.
        providers_sudo = (
            request.env["payment.provider"]
            .sudo()
            ._get_compatible_providers(
                company.id,
                partner_sudo.id,
                amount,
                currency_id=currency.id,
                sale_order_id=order_sudo.id,
                report=availability_report,
                **kwargs,
            )
        )  # In sudo mode to read the fields of providers and partner (if logged out).
        payment_methods_sudo = (
            request.env["payment.method"]
            .sudo()
            ._get_compatible_payment_methods(
                providers_sudo.ids,
                partner_sudo.id,
                currency_id=currency.id,
                sale_order_id=order_sudo.id,
                report=availability_report,
                **kwargs,
            )
        )  # In sudo mode to read the fields of providers.
        tokens_sudo = (
            request.env["payment.token"]
            .sudo()
            ._get_available_tokens(providers_sudo.ids, partner_sudo.id, **kwargs)
        )  # In sudo mode to read the partner's tokens (if logged out) and provider fields.

        # Make sure that the partner's company matches the invoice's company.
        company_mismatch = not payment_portal.PaymentPortal._can_partner_pay_in_company(
            partner_sudo, company
        )

        portal_page_values = {
            "company_mismatch": company_mismatch,
            "expected_company": company,
        }
        payment_form_values = {
            "show_tokenize_input_mapping": PaymentPortal._compute_show_tokenize_input_mapping(
                providers_sudo, sale_order_id=order_sudo.id
            ),
        }
        payment_context = {
            "amount": amount,
            "currency": currency,
            "partner_id": partner_sudo.id,
            "providers_sudo": providers_sudo,
            "payment_methods_sudo": payment_methods_sudo,
            "tokens_sudo": tokens_sudo,
            "availability_report": availability_report,
            "transaction_route": order_sudo.get_portal_url(suffix="/transaction"),
            "landing_route": order_sudo.get_portal_url(),
            "access_token": order_sudo._portal_ensure_token(),
        }
        return {
            **portal_page_values,
            **payment_form_values,
            **payment_context,
            **self._get_extra_payment_form_values(**kwargs),
        }

    # ------------------------------------------------------------
    # ENDPOINTS
    # ------------------------------------------------------------

    # Two following routes cannot be readonly because of the call to `_portal_ensure_token` on all
    # displayed orders, to assign an access token (triggering a sql update on flush)
    @http.route(
        ["/my/quotes", "/my/quotes/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_quotes(self, **kwargs):
        values = self._prepare_sale_portal_rendering_values(
            quotation_page=True, **kwargs
        )
        request.session["my_quotations_history"] = values["quotations"].ids[:100]
        return request.render("sale.portal_my_quotations", values)

    @http.route(
        ["/my/orders", "/my/orders/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_orders(self, **kwargs):
        values = self._prepare_sale_portal_rendering_values(
            quotation_page=False, **kwargs
        )
        request.session["my_orders_history"] = values["orders"].ids[:100]
        return request.render("sale.portal_my_orders", values)

    @http.route(["/my/orders/<int:order_id>"], type="http", auth="public", website=True)
    def portal_order_page(
        self,
        order_id,
        report_type=None,
        access_token=None,
        message=False,
        download=False,
        downpayment=None,
        **kw,
    ):
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return request.redirect("/my")

        if report_type in ("html", "pdf", "text"):
            return self._show_report(
                model=order_sudo,
                report_type=report_type,
                report_ref="sale.action_report_saleorder",
                download=download,
            )

        if request.env.user.share and access_token:
            # If a public/portal user accesses the order with the access token
            # Log a note on the chatter.
            today = fields.Date.today().isoformat()
            session_obj_date = request.session.get("view_quote_%s" % order_sudo.id)
            if session_obj_date != today:
                # store the date as a string in the session to allow serialization
                request.session["view_quote_%s" % order_sudo.id] = today
                # The "Quotation viewed by customer" log note is an information
                # dedicated to the salesman and shouldn't be translated in the customer/website lgg
                context = {
                    "lang": order_sudo.user_id.partner_id.lang
                    or order_sudo.company_id.partner_id.lang
                }
                author = (
                    order_sudo.partner_id
                    if request.env.user._is_public()
                    else request.env.user.partner_id
                )
                msg = _("Quotation viewed by customer %s", author.name)
                del context
                order_sudo.with_user(SUPERUSER_ID).message_post(
                    body=msg,
                    message_type="notification",
                    subtype_xmlid="sale.mt_order_viewed",
                )

        backend_url = (
            f"/odoo/action-{order_sudo._get_portal_return_action().id}/{order_sudo.id}"
        )
        values = {
            "sale_order": order_sudo,
            "product_documents": order_sudo._get_product_documents(),
            "message": message,
            "report_type": "html",
            "backend_url": backend_url,
            "res_company": order_sudo.company_id,  # Used to display correct company logo
        }

        # Payment values
        if order_sudo._has_to_be_paid():
            values.update(
                self._get_payment_values(
                    order_sudo,
                    downpayment=(
                        downpayment == "true"
                        if downpayment is not None
                        else order_sudo.prepayment_percent < 1.0
                    ),
                )
            )

        if order_sudo.state in ("draft", "sent", "cancel"):
            history_session_key = "my_quotations_history"
        else:
            history_session_key = "my_orders_history"

        values = self._get_page_view_values(
            order_sudo, access_token, values, history_session_key, False
        )

        return request.render("sale.sale_order_portal_template", values)

    @http.route(
        ["/my/orders/<int:order_id>/accept"],
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def portal_quote_accept(
        self, order_id, access_token=None, name=None, signature=None
    ):
        # get from query string if not on json param
        access_token = access_token or request.httprequest.args.get("access_token")
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return {"error": _("Invalid order.")}

        if not order_sudo._has_to_be_signed():
            return {
                "error": _("The order is not in a state requiring customer signature.")
            }
        if not signature:
            return {"error": _("Signature is missing.")}

        try:
            order_sudo.write(
                {
                    "signed_by": name,
                    "signed_on": fields.Datetime.now(),
                    "signature": signature,
                }
            )
            request.env.cr.commit()
        except (TypeError, binascii.Error) as e:
            return {"error": _("Invalid signature data.")}

        if not order_sudo._has_to_be_paid():
            order_sudo.with_context(send_email=True).action_confirm()

        pdf = (
            request.env["ir.actions.report"]
            .sudo()
            ._render_qweb_pdf("sale.action_report_saleorder", [order_sudo.id])[0]
        )

        order_sudo.message_post(
            attachments=[("%s.pdf" % order_sudo.name, pdf)],
            author_id=(
                order_sudo.partner_id.id
                if request.env.user._is_public()
                else request.env.user.partner_id.id
            ),
            body=_("Order signed by %s", name),
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

        query_string = "&message=sign_ok"
        if order_sudo._has_to_be_paid():
            query_string += "&allow_payment=yes"
        return {
            "force_refresh": True,
            "redirect_url": order_sudo.get_portal_url(query_string=query_string),
        }

    @http.route(
        ["/my/orders/<int:order_id>/decline"],
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
    )
    def portal_quote_decline(
        self, order_id, access_token=None, decline_message=None, **kwargs
    ):
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return request.redirect("/my")

        if order_sudo._has_to_be_signed() and decline_message:
            order_sudo.action_cancel()
            # The currency is manually cached while in a sudoed environment to prevent an
            # AccessError. The state of the Sales Order is a dependency of
            # `amount_to_invoice_taxexc`, which is a monetary field. They require the currency to
            # ensure the values are saved in the correct format. However, the currency cannot be
            # read directly during the flush due to access rights, necessitating manual caching.
            order_sudo.line_ids.currency_id

            order_sudo.message_post(
                author_id=(
                    order_sudo.partner_id.id
                    if request.env.user._is_public()
                    else request.env.user.partner_id.id
                ),
                body=decline_message,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
            redirect_url = order_sudo.get_portal_url()
        else:
            redirect_url = order_sudo.get_portal_url(
                query_string="&message=cant_reject"
            )

        return request.redirect(redirect_url)

    @http.route(
        "/my/orders/<int:order_id>/document/<int:document_id>",
        type="http",
        auth="public",
        readonly=True,
    )
    def portal_quote_document(self, order_id, document_id, access_token):
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except (AccessError, MissingError):
            return request.redirect("/my")

        document = request.env["product.document"].browse(document_id).sudo().exists()
        if not document or not document.active:
            return request.redirect("/my")

        if document not in order_sudo._get_product_documents():
            return request.redirect("/my")

        return (
            request.env["ir.binary"]
            ._get_stream_from(
                document.ir_attachment_id,
            )
            .get_response(as_attachment=True)
        )
