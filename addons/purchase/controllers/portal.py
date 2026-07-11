import base64
from collections import OrderedDict
from datetime import datetime

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.http import Response, request
from odoo.tools.image import image_process

from odoo.addons.portal.controllers import portal
from odoo.addons.portal.controllers.portal import pager as portal_pager


class CustomerPortal(portal.CustomerPortal):
    # ------------------------------------------------------------------
    # Module-prefixed hooks (Phase 1).
    # Names are purchase-scoped to avoid MRO collision with sale's
    # CustomerPortal in the combined dispatcher built by
    # odoo.http.routing.build_controllers.  Phase 2 will move these
    # to base_order and strip the prefix.
    # ------------------------------------------------------------------

    def _purchase_get_order_model(self):
        """Return the order model name handled by this controller."""
        return "purchase.order"

    def _purchase_get_portal_counters(self):
        """Return the list of ``(counter_key, domain)`` for home-page counters."""
        return [
            ("rfq_count", self._purchase_get_page_state_domain("rfq")),
            ("purchase_count", [("state", "in", ("done", "cancel"))]),
        ]

    def _purchase_get_page_config(self, page_key):
        """Return per-page metadata used by the list-page helper."""
        if page_key == "rfq":
            return {
                "url": "/my/rfq",
                "template": "purchase.portal_my_purchase_rfqs",
                "session_key": "my_rfqs_history",
                "page_name": "rfq",
                "values_key": "rfqs",
            }
        return {
            "url": "/my/purchase",
            "template": "purchase.portal_my_purchase_orders",
            "session_key": "my_purchases_history",
            "page_name": "purchase",
            "values_key": "orders",
            "default_filter": "all",
        }

    def _purchase_get_page_state_domain(self, page_key):
        """Return the state-filter domain for the given list page."""
        if page_key == "rfq":
            return [("state", "=", "sent")]
        # /my/purchase narrows state via searchbar_filters.
        return []

    def _purchase_get_order_searchbar_sortings(self):
        """Return the sort options offered on the order list pages."""
        return {
            "date": {"label": _("Newest"), "order": "create_date desc, id desc"},
            "name": {"label": _("Name"), "order": "name asc, id asc"},
            "amount_total": {
                "label": _("Total"),
                "order": "amount_total desc, id desc",
            },
        }

    def _purchase_get_order_searchbar_filters(self, page_key):
        """Return the filter options offered on the given list page."""
        if page_key != "purchase":
            return {}
        return {
            "all": {
                "label": _("All"),
                "domain": [("state", "in", ("done", "cancel"))],
            },
            "purchase": {
                "label": _("Purchase Order"),
                "domain": [("state", "=", "done")],
            },
            "cancel": {
                "label": _("Cancelled"),
                "domain": [("state", "=", "cancel")],
            },
        }

    def _purchase_get_detail_history_session_key(self, order):
        """Return the session-history key for the single-order detail page."""
        if order.state == "sent":
            return "my_rfqs_history"
        return "my_purchases_history"

    @staticmethod
    def _purchase_detail_report_ref(order_sudo):
        """Return the xmlid of the report rendered for the detail page."""
        if order_sudo.state in ("rfq", "sent"):
            return "purchase.report_purchase_quotation"
        return "purchase.action_report_purchase_order"

    def _purchase_prepare_orders_domain(self, partner, page_key):
        """Return the search domain for a portal order list.

        Partner-scoping is enforced by ``purchase.portal_purchase_order_user_rule``
        for ``base.group_portal`` users, so it is not re-applied here.

        :param res.partner partner: The portal user's partner record.
        :param str page_key: Identifier of the list page.
        :rtype: list
        """
        return list(self._purchase_get_page_state_domain(page_key))

    # ------------------------------------------------------------------
    # Home portal counters: kept unprefixed because the override cooperates
    # via ``super()`` with the upstream chain and sale's override.
    # ------------------------------------------------------------------

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        Order = request.env[self._purchase_get_order_model()]
        can_read = Order.has_access("read")
        for counter_key, domain in self._purchase_get_portal_counters():
            if counter_key in counters:
                values[counter_key] = Order.search_count(domain) if can_read else 0
        return values

    # ------------------------------------------------------------------
    # List page rendering values
    # ------------------------------------------------------------------

    def _purchase_prepare_order_portal_rendering_values(
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

        :param str page_key: Identifier passed to ``_purchase_get_page_config`` and
                             ``_purchase_get_page_state_domain``.
        :rtype: dict
        """
        Order = request.env[self._purchase_get_order_model()]
        partner = request.env.user.partner_id
        cfg = self._purchase_get_page_config(page_key)
        values = self._prepare_portal_layout_values()

        domain = self._purchase_prepare_orders_domain(partner, page_key)
        if date_begin and date_end:
            domain += [
                ("create_date", ">", date_begin),
                ("create_date", "<=", date_end),
            ]

        searchbar_sortings = self._purchase_get_order_searchbar_sortings()
        if not sortby:
            sortby = "date"
        order = searchbar_sortings[sortby]["order"]

        searchbar_filters = self._purchase_get_order_searchbar_filters(page_key)
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
    # Detail page rendering values
    # ------------------------------------------------------------------

    def _purchase_resize_to_48(self, source):
        """Resize a base64-encoded image source to 48x48."""
        if not source:
            source = request.env["ir.binary"]._placeholder()
        else:
            source = base64.b64decode(source)
        return base64.b64encode(image_process(source, size=(48, 48)))

    def _purchase_prepare_order_page_view_values(self, order, access_token, **kwargs):
        """Build the QWeb context dict for the single-order portal page."""
        values = {
            "order": order,
            "resize_to_48": self._purchase_resize_to_48,
            "report_type": "html",
        }
        return self._get_page_view_values(
            order,
            access_token,
            values,
            self._purchase_get_detail_history_session_key(order),
            False,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # List routes
    # ------------------------------------------------------------------

    @http.route(
        ["/my/rfq", "/my/rfq/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_purchase_rfqs(self, **kw):
        values = self._purchase_prepare_order_portal_rendering_values("rfq", **kw)
        return request.render("purchase.portal_my_purchase_rfqs", values)

    @http.route(
        ["/my/purchase", "/my/purchase/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_purchase_orders(self, **kw):
        values = self._purchase_prepare_order_portal_rendering_values("purchase", **kw)
        return request.render("purchase.portal_my_purchase_orders", values)

    # ------------------------------------------------------------------
    # Detail route
    # ------------------------------------------------------------------

    @http.route(
        ["/my/purchase/<int:order_id>"],
        type="http",
        auth="public",
        website=True,
    )
    def portal_my_purchase_order(
        self, order_id=None, access_token=None, message=False, **kw
    ):
        try:
            order_sudo = self._document_check_access(
                "purchase.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
            return request.redirect("/my")

        report_type = kw.get("report_type")
        if report_type in ("html", "pdf", "text"):
            return self._show_report(
                model=order_sudo,
                report_type=report_type,
                report_ref=self._purchase_detail_report_ref(order_sudo),
                download=kw.get("download"),
            )

        # POST-redirect-GET on acknowledge so the action is idempotent on refresh
        # and the result is reflected to the customer via the ?message=ack_ok banner.
        if kw.get("acknowledge"):
            order_sudo.action_acknowledge()
            return request.redirect(
                order_sudo.get_portal_url(query_string="&message=ack_ok")
            )

        values = self._purchase_prepare_order_page_view_values(
            order_sudo, access_token, **kw
        )
        values["message"] = message
        if order_sudo.company_id:
            values["res_company"] = order_sudo.company_id

        if kw.get("update") == "True":
            return request.render(
                "purchase.portal_my_purchase_order_update_date", values
            )
        return request.render("purchase.portal_my_purchase_order", values)

    # ------------------------------------------------------------------
    # Action routes
    # ------------------------------------------------------------------

    @http.route(
        ["/my/purchase/<int:order_id>/update"],
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def portal_my_purchase_order_update_dates(
        self, order_id=None, access_token=None, **kw
    ):
        """Update the scheduled date on one or more purchase order lines from the portal."""
        try:
            order_sudo = self._document_check_access(
                "purchase.order", order_id, access_token=access_token
            )
        except AccessError, MissingError:
            return request.redirect("/my")

        updated_dates = []
        for id_str, date_str in kw.items():
            try:
                line_id = int(id_str)
            except ValueError:
                return request.redirect(order_sudo.get_portal_url())
            line = order_sudo.line_ids.filtered_domain([("id", "=", line_id)])
            if not line:
                return request.redirect(order_sudo.get_portal_url())

            try:
                updated_date = line._convert_to_middle_of_day(
                    datetime.strptime(date_str, "%Y-%m-%d")
                )
            except ValueError:
                continue

            updated_dates.append((line, updated_date))

        if updated_dates:
            order_sudo._update_order_lines_date_planned(updated_dates)
        return Response(status=204)

    @http.route(
        ["/my/purchase/<int:order_id>/download_edi"],
        auth="public",
        website=True,
    )
    def portal_my_purchase_order_download_edi(
        self, order_id=None, access_token=None, **kw
    ):
        """Download the EDI XML representation of a purchase order."""
        try:
            order_sudo = self._document_check_access(
                "purchase.order", order_id, access_token=access_token
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
