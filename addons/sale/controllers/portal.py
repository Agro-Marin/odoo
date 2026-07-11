import binascii
from collections import OrderedDict

from odoo import SUPERUSER_ID, _, fields, http
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.fields import Command
from odoo.http import request

from odoo.addons.payment.controllers import portal as payment_portal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class CustomerPortal(payment_portal.PaymentPortal):
    # ------------------------------------------------------------------
    # Module-prefixed hooks (Phase 1).
    # Names are sale-scoped to avoid MRO collision with purchase's
    # CustomerPortal in the combined dispatcher built by
    # odoo.http.routing.build_controllers.  Phase 2 will move these
    # to base_order and strip the prefix.
    # ------------------------------------------------------------------

    def _sale_get_order_model(self):
        """Return the order model name handled by this controller."""
        return "sale.order"

    def _sale_get_portal_counters(self):
        """Return the list of ``(counter_key, domain)`` for home-page counters."""
        return [
            ("quotation_count", self._sale_get_page_state_domain("quote")),
            ("order_count", self._sale_get_page_state_domain("order")),
        ]

    def _sale_get_page_config(self, page_key):
        """Return per-page metadata used by the list-page helper."""
        if page_key == "quote":
            return {
                "url": "/my/quotes",
                "template": "sale.portal_my_quotations",
                "session_key": "my_quotations_history",
                "page_name": "quote",
                "values_key": "quotations",
            }
        return {
            "url": "/my/orders",
            "template": "sale.portal_my_orders",
            "session_key": "my_orders_history",
            "page_name": "order",
            "values_key": "orders",
            "default_filter": "all",
        }

    def _sale_get_page_state_domain(self, page_key):
        """Return the state-filter domain for the given list page."""
        if page_key == "quote":
            return [("state", "=", "draft"), ("sent", "=", True)]
        return [("state", "in", ("done", "cancel"))]

    def _sale_get_order_searchbar_sortings(self):
        """Return the sort options offered on the order list pages."""
        return {
            "date": {"label": _("Newest"), "order": "create_date desc, id desc"},
            "name": {"label": _("Name"), "order": "name asc, id asc"},
            "amount_total": {
                "label": _("Total"),
                "order": "amount_total desc, id desc",
            },
        }

    def _sale_get_order_searchbar_filters(self, page_key):
        """Return the filter options offered on the given list page."""
        if page_key != "order":
            return {}
        return {
            "all": {
                "label": _("All"),
                "domain": [("state", "in", ("done", "cancel"))],
            },
            "order": {
                "label": _("Sales Order"),
                "domain": [("state", "=", "done")],
            },
            "cancel": {
                "label": _("Cancelled"),
                "domain": [("state", "=", "cancel")],
            },
        }

    def _sale_get_detail_history_session_key(self, order):
        """Return the session-history key for the single-order detail page."""
        if order.state in ("draft", "cancel"):
            return "my_quotations_history"
        return "my_orders_history"

    def _sale_prepare_orders_domain(self, partner, page_key):
        """Return the search domain for a portal order list.

        Partner-scoping is enforced by ``sale.sale_order_rule_portal`` for
        ``base.group_portal`` users, so it is not re-applied here.

        :param res.partner partner: The portal user's partner record.
        :param str page_key: Identifier of the list page.
        :rtype: list
        """
        return list(self._sale_get_page_state_domain(page_key))

    # ------------------------------------------------------------------
    # Home portal counters: kept unprefixed because the override cooperates
    # via ``super()`` with the upstream chain and purchase's override.
    # ------------------------------------------------------------------

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        Order = request.env[self._sale_get_order_model()]
        can_read = Order.has_access("read")
        for counter_key, domain in self._sale_get_portal_counters():
            if counter_key in counters:
                values[counter_key] = Order.search_count(domain) if can_read else 0
        return values

    # ------------------------------------------------------------------
    # List page rendering values
    # ------------------------------------------------------------------

    def _sale_prepare_order_portal_rendering_values(
        self,
        page_key,
        page=1,
        date_begin=None,
        date_end=None,
        sortby=None,
        filterby=None,
        **kwargs,
    ):
        """Build the QWeb context dict shared by both list pages.

        :param str page_key: Identifier passed to ``_sale_get_page_config`` and
                             ``_sale_get_page_state_domain``.
        :rtype: dict
        """
        Order = request.env[self._sale_get_order_model()]
        partner = request.env.user.partner_id
        cfg = self._sale_get_page_config(page_key)
        values = self._prepare_portal_layout_values()

        domain = self._sale_prepare_orders_domain(partner, page_key)
        if date_begin and date_end:
            domain += [
                ("create_date", ">", date_begin),
                ("create_date", "<=", date_end),
            ]

        searchbar_sortings = self._sale_get_order_searchbar_sortings()
        if not sortby:
            sortby = "date"
        order = searchbar_sortings[sortby]["order"]

        searchbar_filters = self._sale_get_order_searchbar_filters(page_key)
        if searchbar_filters:
            if not filterby:
                filterby = cfg.get("default_filter")
            if filterby in searchbar_filters:
                domain += searchbar_filters[filterby]["domain"]

        can_read = Order.has_access("read")
        total = Order.search_count(domain) if can_read else 0
        pager = portal_pager(
            url=cfg["url"],
            url_args={
                "date_begin": date_begin,
                "date_end": date_end,
                "sortby": sortby,
                "filterby": filterby,
            },
            total=total,
            page=page,
            step=self._items_per_page,
        )

        orders = (
            Order.search(
                domain,
                order=order,
                limit=self._items_per_page,
                offset=pager["offset"],
            )
            if can_read
            else Order
        )

        request.session[cfg["session_key"]] = orders.ids[:100]

        values.update(
            {
                "date": date_begin,
                cfg["values_key"]: orders,
                "page_name": cfg["page_name"],
                "pager": pager,
                "default_url": cfg["url"],
                "searchbar_sortings": searchbar_sortings,
                "sortby": sortby,
                "searchbar_filters": OrderedDict(sorted(searchbar_filters.items())),
                "filterby": filterby,
            }
        )
        return values

    # ------------------------------------------------------------------
    # List routes
    # ------------------------------------------------------------------

    # Two following routes cannot be readonly because of the call to `_portal_ensure_token` on all
    # displayed orders, to assign an access token (triggering a sql update on flush)
    @http.route(
        ["/my/quotes", "/my/quotes/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_quotes(self, **kw):
        values = self._sale_prepare_order_portal_rendering_values("quote", **kw)
        return request.render("sale.portal_my_quotations", values)

    @http.route(
        ["/my/orders", "/my/orders/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_orders(self, **kw):
        values = self._sale_prepare_order_portal_rendering_values("order", **kw)
        return request.render("sale.portal_my_orders", values)

    # ------------------------------------------------------------------
    # Detail route
    # ------------------------------------------------------------------

    def _sale_order_get_page_view_values(
        self, order_sudo, access_token, values, history_session_key, **kwargs
    ):
        return self._get_page_view_values(
            order_sudo, access_token, values, history_session_key, False, **kwargs
        )

    @http.route(
        ["/my/orders/<int:order_id>"],
        type="http",
        auth="public",
        website=True,
    )
    def portal_my_order(
        self,
        order_id,
        report_type=None,
        access_token=None,
        message=False,
        download=False,
        payment_amount=None,
        amount_selection=None,
        **kw,
    ):
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
            return request.redirect("/my")

        payment_amount = self._cast_as_float(payment_amount)
        prepayment_amount = order_sudo._get_prepayment_required_amount()
        if (
            payment_amount
            and payment_amount < prepayment_amount
            and order_sudo.state != "done"
        ):
            raise MissingError(_("The amount is lower than the prepayment amount."))

        if report_type in ("html", "pdf", "text"):
            return self._show_report(
                model=order_sudo,
                report_type=report_type,
                report_ref="sale.action_report_saleorder",
                download=download,
            )

        # If the route is fetched from the link previewer avoid triggering that quotation is viewed.
        is_link_preview = request.httprequest.headers.get("Odoo-Link-Preview")
        if request.env.user.share and access_token and is_link_preview != "True":
            # If a public/portal user accesses the order with the access token
            # Log a note on the chatter.
            today = fields.Date.today().isoformat()
            session_obj_date = request.session.get("view_quote_%s" % order_sudo.id)
            if session_obj_date != today:
                # store the date as a string in the session to allow serialization
                request.session["view_quote_%s" % order_sudo.id] = today
                # The "Quotation viewed by customer" log note is an information
                # dedicated to the salesman and shouldn't be translated in the customer/website lang
                lang = (
                    order_sudo.user_id.partner_id.lang
                    or order_sudo.company_id.partner_id.lang
                )
                author = (
                    order_sudo.partner_id
                    if request.env.user._is_public()
                    else request.env.user.partner_id
                )
                msg = (
                    request.env["sale.order"]
                    .with_context(lang=lang)
                    .env._("Quotation viewed by customer %s", author.name)
                )
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
            "payment_amount": payment_amount,
        }

        # Payment values
        if order_sudo._has_to_be_paid() or (
            payment_amount and not order_sudo.is_expired
        ):
            values.update(
                self._get_payment_values(
                    order_sudo,
                    is_down_payment=self._determine_is_down_payment(
                        order_sudo, amount_selection, payment_amount
                    ),
                    payment_amount=payment_amount,
                )
            )
        else:
            values["payment_amount"] = None

        values = self._sale_order_get_page_view_values(
            order_sudo,
            access_token,
            values,
            self._sale_get_detail_history_session_key(order_sudo),
            **kw,
        )

        return request.render("sale.sale_order_portal_template", values)

    def _determine_is_down_payment(self, order_sudo, amount_selection, payment_amount):
        """Determine whether the current payment is a down payment.

        :param sale.order order_sudo: The sales order being paid.
        :param str amount_selection: The amount selection specified in the payment link.
        :param float payment_amount: The amount suggested in the payment link.
        :return: Whether the current payment is a down payment.
        :rtype: bool
        """
        if (
            amount_selection == "down_payment"
        ):  # The customer chose to pay a down payment.
            is_down_payment = True
        elif (
            amount_selection == "full_amount"
        ):  # The customer chose to pay the full amount.
            is_down_payment = False
        else:  # No choice has been specified yet.
            is_down_payment = (
                order_sudo.prepayment_percent < 1.0
                if payment_amount is None
                else payment_amount < order_sudo.amount_total
            )
        return is_down_payment

    def _get_payment_values(
        self, order_sudo, is_down_payment=False, payment_amount=None, **kwargs
    ):
        """Return the payment-specific QWeb context values.

        :param sale.order order_sudo: The sales order being paid.
        :param bool is_down_payment: Whether the current payment is a down payment.
        :param float payment_amount: The amount suggested in the payment link.
        :param dict kwargs: Locally unused data passed to `_get_compatible_providers` and
                            `_get_available_tokens`.
        :return: The payment-specific values.
        :rtype: dict
        """
        company = order_sudo.company_id
        logged_in = not request.env.user._is_public()
        partner_sudo = (
            request.env.user.partner_id if logged_in else order_sudo.partner_id
        )
        currency = order_sudo.currency_id

        if is_down_payment:
            if payment_amount and payment_amount < order_sudo.amount_total:
                amount = payment_amount
            else:
                amount = order_sudo._get_prepayment_required_amount()
        elif order_sudo.state == "done":
            amount = payment_amount or order_sudo.amount_total
        else:
            amount = order_sudo.amount_total

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
            "payment_amount": payment_amount,
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

    # ------------------------------------------------------------------
    # Action routes
    # ------------------------------------------------------------------

    @http.route(
        ["/my/orders/<int:order_id>/accept"],
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def portal_my_order_accept(
        self, order_id, access_token=None, name=None, signature=None
    ):
        # get from query string if not on json param
        access_token = access_token or request.httprequest.args.get("access_token")
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
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
            # flush now to make signature data available to PDF render request
            request.env.cr.flush()
        except TypeError, binascii.Error:
            return {"error": _("Invalid signature data.")}

        if not order_sudo._has_to_be_paid():
            order_sudo._validate_order()

        pdf = (
            request.env["ir.actions.report"]
            .sudo()
            .with_context(sale_include_signature=True)
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
    def portal_my_order_decline(
        self, order_id, access_token=None, decline_message=None, **kw
    ):
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
            return request.redirect("/my")

        if order_sudo._has_to_be_signed() and decline_message:
            order_sudo._action_cancel()
            # The currency is manually cached while in a sudoed environment to prevent an
            # AccessError. The state of the Sales Order is a dependency of
            # `amount_taxexc_to_invoice`, which is a monetary field. They require the currency to
            # ensure the values are saved in the correct format. However, the currency cannot be
            # read directly during the flush due to access rights, necessitating manual caching.
            order_sudo.line_ids.currency_id  # noqa: B018 (intentional: primes the currency cache)

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
    def portal_my_order_document(self, order_id, document_id, access_token):
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
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

    @http.route(
        ["/my/orders/<int:order_id>/download_edi"],
        auth="public",
        website=True,
    )
    def portal_my_order_download_edi(self, order_id=None, access_token=None, **kw):
        """Download the EDI XML representation of a sales order."""
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
            return request.redirect("/my")

        builders = order_sudo._get_edi_builders()

        # This handles only one builder for now, more can be added in the future
        # TODO: add builder choice on modal
        if len(builders) == 0:
            return request.redirect("/my")
        builder = builders[0]

        xml_content = builder._export_order(order_sudo)

        download_name = builder._export_invoice_filename(
            order_sudo
        )  # works even if it's a SO or PO

        http_headers = [
            ("Content-Type", "text/xml"),
            ("Content-Length", len(xml_content)),
            ("Content-Disposition", f"attachment; filename={download_name}"),
        ]
        return request.make_response(xml_content, headers=http_headers)


class PaymentPortal(payment_portal.PaymentPortal):
    @http.route(
        "/my/orders/<int:order_id>/transaction",
        type="jsonrpc",
        auth="public",
    )
    def portal_order_transaction(self, order_id, access_token, **kwargs):
        """Create a draft transaction and return its processing values.

        :param int order_id: The sales order to pay, as a `sale.order` id
        :param str access_token: The access token used to authenticate the request
        :param dict kwargs: Locally unused data passed to `_create_transaction`
        :return: The mandatory values for the processing of the transaction
        :rtype: dict
        :raise: ValidationError if the invoice id or the access token is invalid
        """
        # Check the order id and the access token
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token
            )
        except MissingError:
            raise
        except AccessError:
            raise ValidationError(_("The access token is invalid.")) from None

        logged_in = not request.env.user._is_public()
        partner_sudo = (
            request.env.user.partner_id if logged_in else order_sudo.partner_invoice_id
        )
        self._validate_transaction_kwargs(kwargs)
        kwargs.update(
            {
                "partner_id": partner_sudo.id,
                "currency_id": order_sudo.currency_id.id,
                "sale_order_id": order_id,  # Include the SO to allow Subscriptions tokenizing the tx
            }
        )
        tx_sudo = self._create_transaction(
            custom_create_values={"sale_order_ids": [Command.set([order_id])]},
            **kwargs,
        )

        return tx_sudo._get_processing_values()
