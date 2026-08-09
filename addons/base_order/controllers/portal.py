from collections import OrderedDict

from odoo import _
from odoo.http import request

from odoo.addons.portal.controllers.portal import pager as portal_pager


class OrderPortalMixin:
    """Portal machinery shared by order documents (sale, purchase).

    **Deliberately not an ``http.Controller`` subclass.**
    ``odoo.http.routing.build_controllers`` collects every leaf subclass of a
    top controller and fuses them into a single type, so sale's and purchase's
    ``CustomerPortal`` share one MRO once both modules are installed. Any
    identity-bearing method defined under the same name in both would therefore
    collide, one silently shadowing the other — which is why those hooks carry a
    ``_sale_`` / ``_purchase_`` prefix.

    This class holds only logic that is *identical* for every order type, and
    takes the caller's identity as arguments rather than reading it off ``self``.
    It appears exactly once in the fused MRO, so there is nothing to collide.
    Do not add routes or identity-dependent behaviour here.
    """

    def _order_portal_default_sortings(self):
        """Return the sort vocabulary offered on the order list pages."""
        return {
            "date": {"label": _("Newest"), "order": "create_date desc, id desc"},
            "name": {"label": _("Name"), "order": "name asc, id asc"},
            "amount_total": {
                "label": _("Total"),
                "order": "amount_total desc, id desc",
            },
        }

    def _order_portal_home_counters(self, values, counters, model_name, counter_specs):
        """Fill the home-page counters an order module contributes.

        :param dict values: The rendering values to complete, returned as-is.
        :param list counters: Counter keys the portal home actually asked for.
        :param str model_name: The order model to count on.
        :param list counter_specs: ``(counter_key, domain)`` pairs.
        :rtype: dict
        """
        Order = request.env[model_name]
        can_read = Order.has_access("read")
        for counter_key, domain in counter_specs:
            if counter_key in counters:
                values[counter_key] = Order.search_count(domain) if can_read else 0
        return values

    def _order_portal_rendering_values(
        self,
        model_name,
        cfg,
        base_domain,
        searchbar_sortings,
        searchbar_filters,
        page=1,
        date_begin=None,
        date_end=None,
        sortby=None,
        filterby=None,
        **kwargs,
    ):
        """Build the QWeb context dict shared by every order list page.

        :param str model_name: The order model to search.
        :param dict cfg: Page metadata (url, template, session_key, page_name,
                         values_key, optional default_filter).
        :param list base_domain: Page domain before date and filter narrowing.
        :param dict searchbar_sortings: Sort vocabulary.
        :param dict searchbar_filters: Filter vocabulary, empty to hide filters.
        :rtype: dict
        """
        Order = request.env[model_name]
        values = self._prepare_portal_layout_values()

        domain = list(base_domain)
        if date_begin and date_end:
            domain += [
                ("create_date", ">", date_begin),
                ("create_date", "<=", date_end),
            ]

        # Clamp to the declared vocabulary; an unknown `?sortby=` used to be a
        # KeyError (HTTP 500). `filterby` below is already membership-tested.
        sortby = self._resolve_searchbar_option(searchbar_sortings, sortby, "date")
        order = searchbar_sortings[sortby]["order"]

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

    def _order_portal_edi_response(self, order_sudo):
        """Return the EDI XML download response for an order, or None.

        None means the caller should redirect: no builder is installed for this
        order type, so there is nothing to export.
        """
        builders = order_sudo._get_edi_builders()

        # This handles only one builder for now, more can be added in the future
        # TODO: add builder choice on modal
        if len(builders) == 0:
            return None
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
