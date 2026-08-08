import math
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from werkzeug.exceptions import Forbidden, NotFound

from odoo import SUPERUSER_ID, _
from odoo.exceptions import (
    AccessDenied,
    AccessError,
    MissingError,
    UserError,
    ValidationError,
)
from odoo.http import Controller, content_disposition, request, route
from odoo.tools import clean_context, consteq, single_email_re, str2bool
from odoo.tools.translate import LazyTranslate

from odoo.addons.web.controllers.utils import _is_local_url

_lt = LazyTranslate(__name__)

# --------------------------------------------------
# Misc tools
# --------------------------------------------------


def pager(url, total, page=1, step=30, scope=5, url_args=None):
    """Generate a dict with required value to render `website.pager` template.

    This method computes url, page range to display, ... in the pager.

    Enhanced pager logic for SEO optimization:
    - Shows first and last page in pagination
    - Shows current page with -1 and +1 neighbors
    - Adds ellipses when necessary

    :param str url : base url of the page link
    :param int total : number total of item to be splitted into pages
    :param int page : current page
    :param int step : item per page
    :param int scope : number of page to display on pager
    :param dict url_args : additional parameters to add as query params to page url
    :returns dict
    """
    # A page holds at least one item. ``step`` comes from callers as a page size
    # (often a controller's ``_items_per_page`` or a request-derived value), and
    # 0 or a negative value has no meaning as one: 0 raised ZeroDivisionError and
    # a negative made ``page_count`` negative, which then clamped ``page`` to a
    # negative number and produced ``/page/-3`` links.
    step = max(1, step)
    # Python 3 division yields float; math.ceil returns int — no outer cast needed.
    # ``max(1, ...)``: an empty result set is still one (empty) page. With a
    # literal 0 the clamps below produced ``page_next``/``page_last`` numbered 0
    # — a page that cannot exist, and one ``portal.pager`` only avoids rendering
    # because it happens to hide itself entirely when ``page_count <= 1``. Any
    # other consumer of this dict (a custom pager template, a caller reading
    # ``page_last`` to build a "jump to end" link) read the 0 as real.
    page_count = max(1, math.ceil(max(0, total) / step))

    # ``isdecimal`` and not ``isdigit``: this guard exists so a non-numeric
    # ``page`` degrades to page 1 instead of raising, but ``str.isdigit()`` is a
    # strictly wider test than what ``int()`` accepts. Superscripts and enclosed
    # numerals ('²', '①') are digits to ``isdigit`` and a ``ValueError`` to
    # ``int()`` — so the very input the guard is meant to absorb sailed through
    # it and raised, an HTTP 500 on any paginated portal list. ``isdecimal()``
    # is exactly the Nd category, i.e. exactly what ``int()`` parses in base 10
    # (Arabic-Indic '٣' still works, as it did before).
    page = max(1, min(int(page if str(page).isdecimal() else 1), page_count))

    page_previous = max(1, page - 1)
    page_next = min(page_count, page + 1)

    def get_url(page):
        _url = f"{url}/page/{page}" if page > 1 else url
        if url_args:
            # Drop None-valued args (a None must not serialize to the literal
            # string "None" — the shop passes ``tags=None`` to clear the filter,
            # and the reader then int-parses "None" -> HTTP 500), mirroring how
            # QueryURL already omits falsy values. doseq=True so a list value
            # (e.g. the shop's ``attribute_values``, read back with
            # ``request.args.getlist``) is emitted as repeated ``key=a&key=b``
            # params rather than a single ``key=['a', 'b']`` Python-repr.
            query = {k: v for k, v in url_args.items() if v is not None}
            if query:
                _url = f"{_url}?{urlencode(query, doseq=True)}"
        return _url

    # Build page list based on conditions. ``scope`` is the target width of the
    # dense page window; the constants below are the scope=5 originals rewritten
    # as functions of ``scope`` (page_count<=5 -> <=scope, page<=3 -> <=scope-2,
    # [1,2,3,4] -> range(1, scope), page_count-2 -> page_count-(scope-3),
    # page_count-3 -> page_count-(scope-2), the ±1 middle window -> ±half). For
    # scope=5 this reproduces the previous output byte-for-byte (exhaustively
    # verified); other values now actually take effect instead of being ignored.
    scope = max(scope, 3)  # below 3 the centred window degenerates
    if page_count <= scope:
        page_list = list(range(1, page_count + 1))
    elif page <= scope - 2:
        page_list = list(range(1, scope)) + ["…", page_count]
    elif page >= page_count - (scope - 3):
        page_list = [1, "…"] + list(range(page_count - (scope - 2), page_count + 1))
    else:
        half = (scope - 3) // 2
        window = list(range(page - half, page + half + 1))
        # Emit "…" only over a real gap: with small scopes (e.g. scope=3 the
        # window is just [page]) the window can sit adjacent to the first or
        # last page, and an unconditional ellipsis would cover zero pages
        # (page=2 of 10 rendered [1, "…", 2, "…", 10]). For scope>=5 the
        # branch guards keep the window off both edges, so this reproduces
        # the previous output unchanged.
        page_list = [1]
        if window[0] > 2:
            page_list.append("…")
        page_list += window
        if window[-1] < page_count - 1:
            page_list.append("…")
        page_list.append(page_count)

    pages = [
        {"num": p, "url": get_url(p) if p != "…" else None, "is_current": p == page}
        for p in page_list
    ]

    return {
        "page_count": page_count,
        "offset": (page - 1) * step,
        "page": {"url": get_url(page), "num": page},
        "page_first": {"url": get_url(1), "num": 1},
        "page_previous": {"url": get_url(page_previous), "num": page_previous},
        "page_next": {"url": get_url(page_next), "num": page_next},
        "page_last": {"url": get_url(page_count), "num": page_count},
        "pages": pages,
    }


def get_records_pager(ids, current, with_token=True):
    """Build prev/next URL pair for navigating a portal-displayed record set.

    :param list[int] ids: ordered record ids (the navigation sequence)
    :param current: single recordset positioned within ``ids``
    :param bool with_token: emit an ``access_token`` on the neighbour links.
        Only meaningful for a caller that is itself browsing by token; see
        :func:`_pager_url` for why this is not always on.
    :return: dict with ``prev_record`` / ``next_record`` URLs, each ``False``
             when that side has no navigable neighbour (none at all, or one
             whose URL field is empty). Empty dict if ``current`` is not in
             ``ids`` or the model has neither ``website_url`` nor ``access_url``.
    :rtype: dict
    """
    if current.id not in ids:
        return {}
    if "access_url" in current._fields:
        attr_name = "access_url"
    elif "website_url" in current._fields:
        attr_name = "website_url"
    else:
        return {}

    idx = ids.index(current.id)
    prev_record = idx != 0 and current.browse(ids[idx - 1])
    next_record = idx < len(ids) - 1 and current.browse(ids[idx + 1])

    return {
        "prev_record": _pager_url(prev_record, attr_name, with_token),
        "next_record": _pager_url(next_record, attr_name, with_token),
    }


def _pager_url(record, attr_name, with_token=True):
    """Build a portal pager URL for a single neighbour.

    Returns ``False`` both for a missing neighbour and for a neighbour whose
    URL field is empty, so QWeb's ``t-if`` / ``'disabled' if not prev_record``
    branches in ``portal.record_pager`` both work.

    The empty-URL case used to return the *recordset*, which QWeb then
    stringified straight into the attribute — emitting
    ``<a href="sale.order(42,)">``: a link to a path that cannot exist, plus a
    gratuitous disclosure of the model name and record id in the page source.
    A neighbour with no reachable URL is not navigable, which is exactly what
    the template's disabled state already expresses.

    ``with_token`` exists because ``_portal_ensure_token`` *persists* a token
    when the record has none. Rendering a document page therefore minted and
    stored a permanent bearer capability on up to two **other** records — the
    session-history neighbours, which the customer may never open — as a side
    effect of a GET. For a signed-in customer that token buys nothing: the
    portal route resolves the neighbour through ``_document_check_access``,
    which grants on ACL alone. The token is only load-bearing for a visitor who
    is *themselves* browsing by token, so only that caller asks for it.
    """
    if not record:
        return False
    if not record[attr_name]:
        return False
    if attr_name == "access_url" and with_token:
        return f"{record[attr_name]}?access_token={record._portal_ensure_token()}"
    return record[attr_name]


def _parse_record_id(raw_id):
    """Coerce a user-supplied record id (query/form string) into an int.

    Controllers receive ids as strings and historically crashed with an
    uncaught ``ValueError`` (HTTP 500) on non-numeric input. ``None``/empty
    values mean "no record" and map to ``None``; anything non-numeric raises
    ``NotFound`` — the id namespace simply does not contain that value.

    :param raw_id: raw request value (str, int, or falsy)
    :return: the id as int, or None when no id was provided
    :rtype: int | None
    :raise werkzeug.exceptions.NotFound: on non-numeric input
    """
    if not raw_id:
        return None
    try:
        return int(raw_id)
    except TypeError, ValueError:
        raise NotFound from None


def _parse_bool_param(raw_value):
    """Coerce a user-supplied flag (query/form string) into a bool.

    ``str2bool`` raises ``ValueError`` outside its accepted vocabulary, so
    feeding it a raw request value made ``?use_delivery_as_billing=xyz`` an
    HTTP 500. Every template in-tree emits a value it accepts, so this is not
    a spontaneous failure; it is reachable by editing the URL, by a stale or
    third-party link, and by any override that forwards an unvalidated value.

    Unlike a record id — for which "not an id" genuinely means 404 — an
    unparseable flag has an obvious safe reading: the option was not enabled.
    Only a recognisably true value turns it on.

    :param raw_value: raw request value (str, bool, or falsy)
    :rtype: bool
    """
    return str2bool(raw_value or "false", default=False)


def _parse_callback_url(raw_callback, default):
    """Coerce a client-supplied post-action redirect target into a safe URL.

    ``callback`` reaches the address flow from the form itself -- it is a hidden
    input in ``portal.address_form_fields``, and ``/my/account?redirect=<url>``
    seeds it straight off the query string. It is then used two ways, both of
    which hand the value to the browser:

    * ``discard_url`` in ``portal.address_footer``, rendered as
      ``<a t-att-href="discard_url or '/my/'">Discard</a>``;
    * the ``redirectUrl`` of ``/my/address/submit``'s JSON answer, which
      ``address.js`` feeds to ``redirect()``.

    Neither constrained the value, so ``/my/account?redirect=https://evil.tld``
    rendered an off-site "Discard" link *on the customer's own domain* -- a
    plain open redirect (CWE-601), the pretext half of a credential-phishing
    flow: the link a victim inspects is genuinely their shop's. Protocol-relative
    ``//evil.tld`` worked the same way. ``javascript:`` was already neutralised,
    but by QWeb's attribute sanitiser rather than by anything here, and the JSON
    path is not covered by it at all.

    :func:`_is_local_url` is the same predicate ``web`` already applies to its
    own ``redirect=`` parameters (``/web/login``, ``/web/session/logout``), so
    portal now answers this question the one way the codebase answers it --
    including the ``/\\`` and ignored-character bypasses it already handles.

    :param raw_callback: raw request value
    :param str default: URL to fall back on when the value is not a local path
    :return: a URL that is safe to emit as a link target or redirect
    :rtype: str
    """
    return raw_callback if _is_local_url(raw_callback) else default


def _as_password_field(raw_value):
    """Coerce a raw request value into the string a password field expects.

    Form values are only strings when the part is sent as text; a multipart
    request may present any field as a file, which werkzeug surfaces as a
    ``FileStorage``. A non-string is not a password, so it degrades to the empty
    string — the same thing an omitted field yields, and already rejected.

    :param raw_value: raw request value
    :rtype: str
    """
    return raw_value.strip() if isinstance(raw_value, str) else ""


def _parse_counter_names(raw_counters):
    """Coerce the ``/my/counters`` payload into a list of counter names.

    Every ``_prepare_home_portal_values`` override tests membership
    (``if "sale_order_count" in counters``), so the parameter's contract is
    "a collection of names". It arrives over ``jsonrpc``, where the caller
    chooses the JSON *type*: a number or ``null`` reached the overrides as-is
    and raised ``TypeError: argument of type 'int' is not a container`` — an
    HTTP 500 with a traceback. A bare string was worse than a crash: ``in``
    then matched *substrings*, so ``"x_count"`` silently satisfied every
    override whose name it happened to contain.

    Anything that is not a list/tuple/set of strings means "no counters
    requested", which is the same well-defined answer ``/my/home`` already
    passes (``[]``).

    :param raw_counters: raw jsonrpc value
    :return: the requested counter names
    :rtype: list[str]
    """
    if not isinstance(raw_counters, (list, tuple, set, frozenset)):
        return []
    return [name for name in raw_counters if isinstance(name, str)]


def _build_url_w_params(url_string, query_params, remove_duplicates=True):
    """Rebuild a string url based on url_string and correctly compute query parameters
    using those present in the url and those given by query_params. Having duplicates in
    the final url is optional. For example:

     * url_string = '/my?foo=bar&error=pay'
     * query_params = {'foo': 'bar2', 'alice': 'bob'}
     * if remove duplicates: result = '/my?foo=bar2&error=pay&alice=bob'
     * else: result = '/my?foo=bar&error=pay&foo=bar2&alice=bob'
    """
    url = urlsplit(url_string)
    # keep_blank_values=True: preserve empty-valued params (``?search=``) the
    # way werkzeug's url.decode_query() did; stdlib parse_qsl drops them by
    # default, silently losing e.g. an empty search filter on portal lists.
    if remove_duplicates:
        url_params = dict(parse_qsl(url.query, keep_blank_values=True))
        url_params.update(query_params)
    else:
        url_params = parse_qsl(url.query, keep_blank_values=True) + list(
            query_params.items()
        )
    return urlunsplit(url._replace(query=urlencode(url_params)))


class CustomerPortal(Controller):
    _items_per_page = 80

    # Headers applied to portal pages that should not be embeddable in a frame
    # (clickjacking protection). Reused across /my/account, /my/security and
    # /my/deactivate_account responses.
    _FRAME_OPTIONS_HEADERS = {
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
    }

    # Parameter names the address flow passes to itself. The address routes
    # forward every *unrecognised* client key onward as ``**kwargs`` -- that is
    # the documented extension point (``_handle_extra_form_data`` and the
    # ``_validate_address_values`` overrides in the l10n modules rely on it) --
    # and those kwargs eventually reach ``_validate_address_values``,
    # ``_is_commercial_address``, ``_complete_address_values`` and
    # ``res.partner._get_current_partner``. A client key that happens to match
    # one of their parameters is therefore not extra data at all: it either
    # duplicates an argument the caller already passes positionally, or it
    # lands in a typed parameter as a raw string. Both are HTTP 500s on routes
    # any logged-in customer can reach -- confirmed for ``partner_sudo``
    # (``TypeError: ... got multiple values for argument 'partner_sudo'``) and,
    # with ``website_sale`` installed, for ``order_sudo``
    # (``AttributeError: 'str' object has no attribute '_is_anonymous_cart'``).
    #
    # These names are supplied by server code, never by a form field or query
    # string, so dropping them from client input costs nothing and closes the
    # whole class. Subclasses that add their own trusted kwarg extend the set
    # through ``_get_reserved_address_form_keys``.
    #
    # ``verify_address_values`` is in the set for a stronger reason than the
    # rest: it is not merely an argument that collides, it is a *trust* switch.
    # Server-side callers (``website_event_sale``, ``website_appointment_sale``)
    # pass ``verify_address_values=False`` to skip validation they have already
    # done themselves, and it travelled in the same ``**form_data`` bag as the
    # customer's own field values -- so ``POST /my/address/submit`` with a bare
    # ``verify_address_values=`` (empty string, i.e. falsy) turned every check in
    # ``_validate_address_values`` off. See ``_create_or_update_address`` for the
    # second, independent guard.
    _RESERVED_ADDRESS_FORM_KEYS = frozenset(
        {
            "address_values",
            "error_messages",
            "extra_form_data",
            "invalid_fields",
            "is_commercial_address",
            "missing_fields",
            "partner_sudo",
            "verify_address_values",
        }
    )

    def _get_reserved_address_form_keys(self):
        """Client keys that must never survive into the address flow's kwargs.

        :return: reserved parameter names
        :rtype: frozenset[str]
        """
        return self._RESERVED_ADDRESS_FORM_KEYS

    def _sanitize_client_address_params(self, client_params):
        """Drop reserved names from client-supplied form data / query params.

        Applied at the route boundary, before any value is forwarded as
        ``**kwargs``, so every method downstream can keep its plain signature.

        :param dict client_params: raw request values
        :return: the same mapping without reserved keys
        :rtype: dict
        """
        reserved = self._get_reserved_address_form_keys()
        return {
            key: value for key, value in client_params.items() if key not in reserved
        }

    def _prepare_portal_layout_values(self):
        """Values for /my/* templates rendering.

        Does not include the record counts.
        """
        # Resolve the customer's sales rep: own assigned user wins, otherwise fall
        # back to the commercial partner's. Public users (portal placeholder) are
        # skipped on both candidates.
        sales_user_sudo = request.env["res.users"]
        partner_sudo = request.env.user.partner_id
        for candidate in (
            partner_sudo.user_id,
            partner_sudo.commercial_partner_id.user_id,
        ):
            if candidate and not candidate._is_public():
                sales_user_sudo = candidate
                break

        return {
            "sales_user": sales_user_sudo,
            "page_name": "home",
        }

    def _resolve_searchbar_option(self, options, key, default):
        """Clamp a client-supplied searchbar key to the vocabulary the page declares.

        ``sortby`` / ``filterby`` / ``groupby`` / ``search_in`` reach a portal
        list route straight off the query string, and the established pattern in
        every consumer is::

            if not sortby:
                sortby = "date"
            order = searchbar_sortings[sortby]["order"]

        which answers ``?sortby=anything-else`` with ``KeyError`` — an HTTP 500
        on a page a logged-in customer can reach by editing the URL, following a
        stale bookmark, or clicking a link built against an older revision of the
        page (the vocabularies are module-specific and change between versions).
        The same values are indexed again by ``portal.portal_searchbar``, so an
        unclamped key can also fail during rendering.

        An unknown sort/filter key has an obvious safe reading — the page's own
        default ordering — unlike a record id, for which "not an id" means 404.
        Returning the default also keeps the rendered searchbar honest: the
        template highlights the returned key, so the customer sees which option
        is actually in effect.

        Living here rather than in each consumer is the point: portal owns the
        template that renders these vocabularies and the pager that pages
        through their results, so it should also own the one rule that says a
        key must be one of them.

        :param dict options: the declared vocabulary (e.g. ``searchbar_sortings``)
        :param key: the client-supplied key; may be ``None``, absent or unknown
        :param str default: key to fall back on; returned as-is when
                            ``options`` itself does not contain it, so a caller
                            with an empty vocabulary still gets a usable value
        :return: a key that is safe to index ``options`` with when
                 ``default`` is one of its keys
        """
        if isinstance(key, str) and key in options:
            return key
        return default

    def _prepare_home_portal_values(self, counters):
        """Values for /my & /my/home routes template rendering.

        Includes the record count for the displayed badges.
        where 'counters' is the list of the displayed badges
        and so the list to compute.
        """
        return {}

    @route(["/my/counters"], type="jsonrpc", auth="user", website=True, readonly=True)
    def counters(self, counters, **kw):
        cache = request.session.get("portal_counters", {}).copy()
        res = self._prepare_home_portal_values(_parse_counter_names(counters))
        cache.update({k: bool(v) for k, v in res.items() if k.endswith("_count")})
        if cache != request.session.get("portal_counters"):
            request.session["portal_counters"] = cache
        return res

    @route(
        ["/my", "/my/home"],
        type="http",
        auth="user",
        website=True,
        list_as_website_content=_lt("User Dashboard"),
    )
    def home(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update(self._prepare_home_portal_values([]))
        return request.render("portal.portal_my_home", values)

    @route(["/my/account"], type="http", auth="user", website=True)
    def account(self, **kwargs):
        response = request.render(
            "portal.portal_my_details",
            self._prepare_my_account_rendering_values(**kwargs),
        )
        for header, value in self._FRAME_OPTIONS_HEADERS.items():
            response.headers[header] = value
        return response

    def _prepare_my_account_rendering_values(self, redirect="/my", **kwargs):
        """Prepare the rendering values for the /my/account route template.

        :param str redirect: route to redirect to after the address update
        :param dict kwargs: unused parameters available for overrides
        :return: The rendering values
        :rtype: dict
        """
        return {
            "page_name": "my_details",
            **self._prepare_portal_layout_values(),
            **self._prepare_address_form_values(
                partner_sudo=request.env.user.partner_id,
                # Main address should always have delivery & billing information set
                use_delivery_as_billing=True,
                callback=redirect,
            ),
        }

    @route("/my/addresses", type="http", auth="user", readonly=True, website=True)
    def my_addresses(self, **query_params):
        """Display the user's addresses."""
        partner_sudo = request.env.user.partner_id  # env.user is always sudoed
        # Same treatment as the two sibling address routes: this one also splats
        # its query string into methods that reach
        # ``res.partner._get_current_partner``. It was harmless only because
        # ``_prepare_address_data`` ignores its kwargs; the editable-address
        # lookup below is a second consumer, so sanitise at the boundary rather
        # than relying on every consumer to be indifferent.
        query_params = self._sanitize_client_address_params(query_params)
        address_data = self._prepare_address_data(partner_sudo, **query_params)
        has_invoice_type_address = any(
            address.type == "invoice" for address in address_data["billing_addresses"]
        )
        # Resolved once for every address on the page rather than per card:
        # ``portal.address_list`` used to call the singleton predicate inside its
        # ``t-foreach``, which costs a ``search_count`` (and its record-rule
        # machinery) per address. See
        # ``res.partner._filter_editable_by_current_customer``.
        all_addresses = (
            address_data["billing_addresses"] | address_data["delivery_addresses"]
        )
        values = {
            "partner_sudo": partner_sudo,
            **address_data,
            "editable_addresses": all_addresses._filter_editable_by_current_customer(
                **query_params
            ),
            "page_name": "my_addresses",
            # One unique address
            "use_delivery_as_billing": not has_invoice_type_address,
            "address_url": "/my/address",
        }
        return request.render("portal.my_addresses", values)

    def _prepare_address_data(self, partner_sudo, /, **_kwargs):
        """Provide the data of the current customer addresses.

        ``partner_sudo`` is positional-only for the same reason as in
        :meth:`_get_page_view_values`: ``/my/addresses`` splats its query string
        in here, so ``?partner_sudo=x`` used to supply a second value for an
        argument the caller already passes positionally (HTTP 500). The name now
        lands in ``_kwargs``, which is ignored.

        Gives the addresses the customer can use, including:
            * his own addresses
            * the addresses belonging to his commercial partner, if complete because
              he cannot edit those addresses.

        :param res.partner partner_sudo: The current user partner.
        :param dict _kwargs: unused parameters available for potential overrides.
        :return: A dictionary holding the current customer billing and delivery addresses.
        :rtype: dict
        """
        partner_sudo = partner_sudo.with_context(show_address=1)
        commercial_partner_sudo = partner_sudo.commercial_partner_id
        # Through the model, like its delivery counterpart just below. The
        # billing domain was the only one of the pair spelled out inline here,
        # so a localisation could override which contacts count as delivery
        # addresses but had no way to say the same thing about billing ones --
        # an asymmetry in the extension surface with no reason behind it.
        billing_partners_sudo = (
            partner_sudo.search(
                commercial_partner_sudo._get_billing_address_domain(),
                order="id desc",
            )
            | partner_sudo
        )
        delivery_partners_sudo = (
            partner_sudo.search(
                commercial_partner_sudo._get_delivery_address_domain(),
                order="id desc",
            )
            | partner_sudo
        )

        if partner_sudo != commercial_partner_sudo:  # Child of the commercial partner.
            # Don't display the commercial partner's addresses if they are not complete, as its
            # children can't edit them.
            if not self._check_billing_address(commercial_partner_sudo):
                billing_partners_sudo -= commercial_partner_sudo
            if not self._check_delivery_address(commercial_partner_sudo):
                delivery_partners_sudo -= commercial_partner_sudo

        return {
            "billing_addresses": billing_partners_sudo,
            "delivery_addresses": delivery_partners_sudo,
        }

    def _check_billing_address(self, partner_sudo):
        """Check that all mandatory billing fields are filled for the given partner.

        :param res.partner partner_sudo: The partner whose billing address to check.
        :return: Whether all mandatory fields are filled.
        :rtype: bool
        """
        mandatory_billing_fields = self._get_mandatory_billing_address_fields(
            partner_sudo.country_id
        )
        return self._has_all_address_fields(partner_sudo, mandatory_billing_fields)

    def _get_mandatory_billing_address_fields(self, country_sudo):
        """Return the set of mandatory billing field names.

        :param res.country country_sudo: The country to use to build the set of mandatory fields.
        :return: The set of mandatory billing field names.
        :rtype: set
        """
        return self._get_mandatory_address_form_fields(country_sudo)

    def _check_delivery_address(self, partner_sudo):
        """Check that all mandatory delivery fields are filled for the given partner.

        :param res.partner partner_sudo: The partner whose delivery address to check.
        :return: Whether all mandatory fields are filled.
        :rtype: bool
        """
        mandatory_delivery_fields = self._get_mandatory_delivery_address_fields(
            partner_sudo.country_id
        )
        return self._has_all_address_fields(partner_sudo, mandatory_delivery_fields)

    def _has_all_address_fields(self, partner_sudo, field_names):
        """Whether every named field is set on ``partner_sudo``.

        Reads the fields off the record rather than through ``read()``. The
        latter answers with a dict that *always* carries ``id`` — a value that
        is true by construction — so the ``all(...)`` it fed was testing one key
        that can never fail, next to the ones that can. It also cost a separate
        round trip per call (this is asked twice per ``/my/addresses`` render)
        where the ORM cache already holds the values.

        :param res.partner partner_sudo: partner to inspect (may be empty)
        :param field_names: field names that must all be filled
        :rtype: bool
        """
        if not partner_sudo:
            return False
        return all(partner_sudo[field_name] for field_name in field_names)

    def _get_mandatory_delivery_address_fields(self, country_sudo):
        """Return the set of mandatory delivery field names.

        :param res.country country_sudo: The country to use to build the set of mandatory fields.
        :return: The set of mandatory delivery field names.
        :rtype: set
        """
        return self._get_mandatory_address_form_fields(country_sudo)

    def _get_mandatory_address_form_fields(self, country_sudo):
        """Identity + geography fields required by both billing and delivery forms.

        Shared base for the two variants above. Localization modules override
        the billing variant to add VAT/IBAN; delivery has no such overrides
        today, but the hook surface is preserved.

        :param res.country country_sudo: country driving the geography requirements.
        :return: required field names (identity + ``_get_mandatory_address_fields``).
        :rtype: set
        """
        base_fields = {"name", "email"}
        if not self._needs_address():
            return base_fields
        base_fields.add("phone")  # not required for quick checkout (event)
        return base_fields | self._get_mandatory_address_fields(country_sudo)

    def _needs_address(self):
        """Hook meant to be overridden in other modules."""
        return True

    def _get_mandatory_address_fields(self, country_sudo):
        """Return the set of common mandatory address fields.

        :param res.country country_sudo: The country to use to build the set of mandatory fields.
        :return: The set of common mandatory address field names.
        :rtype: set
        """
        field_names = {"street", "city", "country_id"}
        if country_sudo.state_required:
            field_names.add("state_id")
        if country_sudo.zip_required:
            field_names.add("zip")
        return field_names

    @route(
        "/my/address",
        type="http",
        methods=["GET"],
        auth="user",
        website=True,
        sitemap=False,
        readonly=True,
    )
    def portal_address(
        self,
        partner_id=None,
        address_type="billing",
        use_delivery_as_billing=False,
        **query_params,
    ):
        """Display the address form.

        A partner and/or an address type can be given through the query string params to specify
        which address to update or create, and its type.

        :param str partner_id: The partner to update with the address form, if any, as a
            `res.partner` id.
        :param str address_type: The type of the address: 'billing' or 'delivery'.
        :param str use_delivery_as_billing: Whether the provided address should be used as both the
                                            delivery and the billing address. 'true' or 'false'.
        :param dict query_params: The additional query string parameters forwarded to
                                  `_prepare_address_form_values`.
        :return: The rendered address form.
        :rtype: str
        """
        partner_sudo = (
            request.env["res.partner"]
            .with_context(show_address=1)
            .sudo()
            .browse(_parse_record_id(partner_id))
        )

        if partner_sudo and not partner_sudo._can_be_edited_by_current_customer():
            raise Forbidden

        # ``query_params`` is forwarded as **kwargs all the way to
        # ``res.partner._get_current_partner``; see _RESERVED_ADDRESS_FORM_KEYS.
        query_params = self._sanitize_client_address_params(query_params)

        address_form_values = {
            **self._prepare_address_form_values(
                partner_sudo,
                address_type=address_type,
                use_delivery_as_billing=_parse_bool_param(use_delivery_as_billing),
                **query_params,
            ),
            "page_name": "address_form",
        }
        return request.render("portal.address_management", address_form_values)

    def _prepare_address_form_values(
        self,
        partner_sudo,
        address_type="billing",
        use_delivery_as_billing=False,
        callback="",
        **kwargs,
    ):
        """Prepare the rendering values of the address form.

        :param partner_sudo: The partner whose address to update through the address form.
        :param str address_type: The type of the address: 'billing' or 'delivery'.
        :param bool use_delivery_as_billing: Whether the provided address should be used as both the
                                             billing and the delivery address.
        :param str callback: The URL to redirect to in case of successful address creation/update.
        :param dict kwargs: additional parameters, forwarded to other methods as well.
        :return: The address page values.
        :rtype: dict
        """
        # ``callback`` is echoed into the page twice -- as the ``Discard`` link's
        # href (``discard_url``) and as a hidden input that comes back on submit.
        # ``/my/account?redirect=<url>`` seeds it straight from the query string,
        # so it is client input on every render. Empty (not the route default)
        # when it is not a local path, which keeps the ``callback or ...``
        # fallbacks below and in the template working unchanged.
        callback = _parse_callback_url(callback, "")

        current_partner = request.env["res.partner"]._get_current_partner(**kwargs)
        commercial_partner = (
            current_partner.commercial_partner_id
        )  # handling commercial fields

        # TODO in the future: rename can_edit_vat
        # Means something like 'can edit commercial fields on current address'
        if partner_sudo:
            # Existing address, use the values defined on the address
            state_id = partner_sudo.state_id.id
            country_sudo = partner_sudo.country_id
            can_edit_vat = partner_sudo.can_edit_vat()
        else:
            # New address, take default values from current partner
            country_sudo = current_partner.country_id or self._get_default_country(
                **kwargs
            )
            state_id = current_partner.state_id.id
            can_edit_vat = not current_partner or (
                partner_sudo == current_partner and current_partner.can_edit_vat()
            )
        address_fields = (country_sudo and country_sudo.get_address_fields()) or [
            "city",
            "zip",
        ]

        return {
            "partner_sudo": partner_sudo,  # If set, customer is editing an existing address
            "partner_id": partner_sudo.id,
            "current_partner": current_partner,
            "commercial_partner": commercial_partner,
            "is_commercial_address": not current_partner
            or partner_sudo == commercial_partner,
            "is_main_address": not current_partner
            or (partner_sudo and partner_sudo == current_partner),
            "commercial_address_update_url": (
                # Only redirect to account update if the logged in user is their own commercial
                # partner.
                current_partner == commercial_partner
                and "/my/account?redirect=/my/addresses"
            ),
            "address_type": address_type,
            "can_edit_vat": can_edit_vat,
            "can_edit_country": not partner_sudo.country_id
            or partner_sudo._can_edit_country(),
            "callback": callback,
            "country": country_sudo,
            "countries": request.env["res.country"].sudo().search([]),
            "is_used_as_billing": address_type == "billing" or use_delivery_as_billing,
            "use_delivery_as_billing": use_delivery_as_billing,
            "state_id": state_id,
            "country_states": country_sudo.state_ids,
            "zip_before_city": (
                "zip" in address_fields
                and address_fields.index("zip") < address_fields.index("city")
            ),
            "vat_label": request.env._("VAT"),
            "discard_url": callback or "/my/addresses",
        }

    def _get_default_country(self, **kwargs):
        """Get country of current user country as default."""
        return request.env.user.country_id

    @route(
        "/my/address/submit",
        type="http",
        methods=["POST"],
        auth="user",
        website=True,
        sitemap=False,
    )
    def portal_address_submit(self, partner_id=None, **form_data):
        """Create or update an address from portal and redirect to appropriate page.

        If it succeeds, it returns the URL to redirect (client-side) to. If it fails (missing or
        invalid information), it highlights the problematic form input with the appropriate error
        message.

        :param str partner_id: The partner whose address to update with the address form, if any.
        :param dict form_data: The form data to process as address values.
        :return: A JSON-encoded feedback, with either the success URL or an error message.
        :rtype: str
        """
        partner_sudo = (
            request.env["res.partner"]
            .with_context(show_address=1)
            .sudo()
            .browse(_parse_record_id(partner_id))
        )
        if partner_sudo and not partner_sudo._can_be_edited_by_current_customer():
            raise Forbidden

        # ``form_data`` is splatted into ``_create_or_update_address`` (which
        # already receives ``partner_sudo`` positionally) and from there into
        # the validation chain; see _RESERVED_ADDRESS_FORM_KEYS.
        form_data = self._sanitize_client_address_params(form_data)

        _partner_sudo, feedback_dict = self._create_or_update_address(
            partner_sudo, **form_data
        )

        return request.make_json_response(feedback_dict)

    def _create_or_update_address(
        self,
        partner_sudo,
        address_type="billing",
        use_delivery_as_billing=False,
        callback="/my/addresses",
        required_fields=False,
        verify_address_values=True,
        **form_data,
    ):
        """Create or update an address if there is no error else return error dict.

        :param str partner_id: The partner whose address to update with the address form, if any.
        :param str address_type: The type of the address: 'billing' or 'delivery'.
        :param dict form_data: The form data to process as address values.
        :param str use_delivery_as_billing: Whether the provided address should be used as both the
                                            billing and the delivery address. 'true' or 'false'.
        :param str callback: The URL to redirect to in case of successful address creation/update.
        :param str required_fields: The additional required address values, as a comma-separated
                                    list of `res.partner` fields.
        :param bool verify_address_values: Whether we want to check the given address values.
            Server-side flag only: see the coercion below.
        :return: Partner record and A JSON-encoded feedback, with either the success URL or
                 an error message.
        :rtype: res.partner, dict
        """
        # ``is not False``: this parameter selects the *trust level* of the call,
        # not a value the customer gets to state. Only server-side callers set
        # it -- ``website_event_sale`` and ``website_appointment_sale`` pass the
        # literal ``False`` because they validate the address themselves first --
        # yet it arrives through the same ``**form_data`` splat as the form's own
        # fields. A truthiness test therefore accepted the *empty string* a
        # request can trivially supply, and ``POST /my/address/submit`` with
        # ``verify_address_values=`` skipped the whole of
        # ``_validate_address_values``: e-mail syntax, VAT, required fields, the
        # country/name/e-mail mutation locks, and the commercial-field
        # propagation rules that also *pop* ``vat``/``company_name`` off a
        # sub-address. Verified against a live portal session: a logged-in
        # customer renamed their own partner and set an unparseable e-mail.
        #
        # ``_RESERVED_ADDRESS_FORM_KEYS`` already strips the name at the two
        # portal routes and at website_sale's. This second guard is what covers
        # the callers that splat raw request data in without sanitising it
        # (``point_of_sale``'s self-order invoice route does), and it is the one
        # that cannot be forgotten by a future call site.
        verify_address_values = verify_address_values is not False
        use_delivery_as_billing = _parse_bool_param(use_delivery_as_billing)
        # Answered to the browser as ``redirectUrl``; never let the request pick
        # an off-site target. See :func:`_parse_callback_url`.
        callback = _parse_callback_url(callback, "/my/addresses")

        # Parse form data into address values, and extract incompatible data as extra form data.
        address_values, extra_form_data = self._parse_form_data(form_data)

        if verify_address_values:
            # Validate the address values and highlights the problems in the form, if any.
            invalid_fields, missing_fields, error_messages = (
                self._validate_address_values(
                    address_values,
                    partner_sudo,
                    address_type,
                    use_delivery_as_billing,
                    required_fields or "",
                    **extra_form_data,
                )
            )
            if error_messages:
                return partner_sudo, {
                    "invalid_fields": list(invalid_fields | missing_fields),
                    "messages": error_messages,
                }

        if not partner_sudo:  # Creation of a new address.
            self._complete_address_values(
                address_values, address_type, use_delivery_as_billing, **form_data
            )
            create_context = clean_context(request.env.context)
            create_context.update(
                {
                    "tracking_disable": True,
                    "no_vat_validation": True,  # Already verified in _validate_address_values
                }
            )
            partner_sudo = (
                request.env["res.partner"]
                .sudo()
                .with_context(create_context)
                .create(address_values)
            )
            if hasattr(partner_sudo, "_onchange_phone_validation"):
                # The `phone_validation` module is installed.
                partner_sudo._onchange_phone_validation()
        elif not self._are_same_addresses(address_values, partner_sudo):
            # If name is not changed then pop it from the address_values, as it affects the bank account holder name
            # `... or ""`: a Char field's cache value can be None (not ""), which
            # would make `.strip()` raise AttributeError.
            if (address_values.get("name") or "").strip() == (
                partner_sudo.name or ""
            ).strip():
                address_values.pop("name", None)
            partner_sudo.write(
                address_values
            )  # Keep the same partner if nothing changed.
            if "phone" in address_values and hasattr(
                partner_sudo, "_onchange_phone_validation"
            ):
                # The `phone_validation` module is installed.
                partner_sudo._onchange_phone_validation()

        if (
            "company_name" in address_values
            and partner_sudo.commercial_partner_id != partner_sudo
            and partner_sudo.commercial_partner_id.is_company
        ):
            # If partner is an individual, update existing company's name or remove one
            company_name = address_values["company_name"]
            parent_company = partner_sudo.commercial_partner_id
            partner_sudo.company_name = False

            if company_name and parent_company and parent_company.name != company_name:
                parent_company.name = company_name

        self._handle_extra_form_data(extra_form_data, address_values)

        return partner_sudo, {"redirectUrl": callback}

    def _parse_form_data(self, form_data):
        """Parse the form data and return them converted into address values and extra form data.

        :param dict form_data: The form data to convert to address values.
        :return: A tuple of converted address values and extra form data.
        :rtype: tuple[dict, dict]
        """
        address_values = {}
        extra_form_data = {}

        ResPartner = request.env["res.partner"]
        partner_fields = ResPartner._fields
        authorized_partner_fields = ResPartner._get_frontend_writable_fields()
        for key, value in form_data.items():
            if isinstance(value, str):
                value = value.strip()
            if key in partner_fields and key in authorized_partner_fields:
                field = partner_fields[key]
                if (
                    field.type == "many2one"
                    and isinstance(value, str)
                    and value.isdigit()
                ):
                    address_values[key] = field.convert_to_cache(int(value), ResPartner)
                else:
                    # Always keep field values, even if falsy, as it might be for resetting a field.
                    address_values[key] = field.convert_to_cache(value, ResPartner)
            elif value:  # The value cannot be saved on the `res.partner` model.
                extra_form_data[key] = value

        if "zipcode" in form_data and not form_data.get("zip"):
            zipcode = form_data.pop("zipcode", "")
            if isinstance(zipcode, str):
                zipcode = zipcode.strip()
            # Through the field, like every value the loop above stores. This
            # alias was the one path that wrote a raw request value straight
            # into ``address_values``, so ``zip`` arrived in a different shape
            # from its siblings and skipped whatever ``convert_to_cache`` does
            # for a Char (notably normalising ``False``/``None`` to "").
            address_values["zip"] = partner_fields["zip"].convert_to_cache(
                zipcode, ResPartner
            )
            # zipcode was collected into extra_form_data by the loop above
            # (it is not a partner field); drop the now-consumed entry so
            # _handle_extra_form_data overrides don't see a stale alias.
            extra_form_data.pop("zipcode", None)

        return address_values, extra_form_data

    def _validate_address_values(
        self,
        address_values,
        partner_sudo,
        address_type,
        use_delivery_as_billing,
        required_fields,
        **kwargs,
    ):
        """Validate the address values and return the invalid fields, the missing fields, and any
        error messages.

        :param dict address_values: The address values to validates.
        :param res.partner partner_sudo: The partner whose address values to validate, if any (can
                                         be empty).
        :param str address_type: The type of the address: 'billing' or 'delivery'.
        :param bool use_delivery_as_billing: Whether the provided address should be used as both the billing and
                              the delivery address.
        :param str required_fields: The additional required address values, as a comma-separated
                                    list of `res.partner` fields.
        :param dict kwargs: Extra form data, available for overrides and some method calls.
        :return: The invalid fields, the missing fields, and any error messages.
        :rtype: tuple[set, set, list]
        """
        invalid_fields = set()
        missing_fields = set()
        error_messages = []

        is_commercial_address = self._is_commercial_address(partner_sudo, **kwargs)

        self._validate_address_partner_mutations(
            address_values,
            partner_sudo,
            is_commercial_address,
            invalid_fields,
            error_messages,
            **kwargs,
        )
        self._validate_address_email_format(
            address_values, invalid_fields, error_messages
        )
        self._validate_address_vat_format(
            address_values, invalid_fields, error_messages
        )
        self._validate_address_required_fields(
            address_values,
            address_type,
            use_delivery_as_billing,
            required_fields,
            is_commercial_address,
            missing_fields,
            error_messages,
        )

        return invalid_fields, missing_fields, error_messages

    def _is_commercial_address(self, partner_sudo, **kwargs):
        """Whether the address is (or will be) the customer's commercial entity.

        :param res.partner partner_sudo: target partner; empty when creating.
        :return: True if ``partner_sudo`` is its own commercial partner; or, when
                 empty, True iff the caller is a public user (so the new address
                 is the future main commercial address).
        :rtype: bool
        """
        if partner_sudo:
            return partner_sudo == partner_sudo.commercial_partner_id
        return not request.env["res.partner"]._get_current_partner(**kwargs)

    def _validate_address_partner_mutations(
        self,
        address_values,
        partner_sudo,
        is_commercial_address,
        invalid_fields,
        error_messages,
        **kwargs,
    ):
        """Existing-partner mutation rules: country / name / email / VAT and
        commercial-field propagation.

        Mutates ``invalid_fields`` and ``error_messages``; may pop disallowed
        keys from ``address_values`` (commercial fields, ``company_name``).
        """
        if not partner_sudo:
            return

        name_change = (
            "name" in address_values
            and partner_sudo.name
            and address_values["name"] != partner_sudo.name.strip()
        )
        country_change = (
            "country_id" in address_values
            and partner_sudo.country_id
            and address_values["country_id"] != partner_sudo.country_id.id
        )
        email_change = (
            "email" in address_values
            and partner_sudo.email
            and address_values["email"] != partner_sudo.email
        )

        # Prevent changing the partner country if documents have been issued.
        if country_change and not partner_sudo._can_edit_country():
            invalid_fields.add("country_id")
            error_messages.append(
                _(
                    "Changing your country is not allowed once document(s) have been issued for your"
                    " account. Please contact us directly for this operation."
                )
            )

        # Prevent changing the partner name or email if it is an internal user.
        if (name_change or email_change) and not all(
            partner_sudo.user_ids.mapped("share")
        ):
            if name_change:
                invalid_fields.add("name")
            if email_change:
                invalid_fields.add("email")
            error_messages.append(
                _(
                    "If you are ordering for an external person, please place your order via the"
                    " backend. If you wish to change your name or email address, please do so in"
                    " the account settings or contact your administrator."
                )
            )

        if not is_commercial_address:
            self._enforce_commercial_field_propagation(
                address_values, partner_sudo, invalid_fields, error_messages, **kwargs
            )
        elif (
            "vat" in address_values
            and partner_sudo.vat
            and address_values["vat"] != partner_sudo.vat
            and not partner_sudo.can_edit_vat()
        ):
            # Commercial partner with documents already issued: VAT is frozen.
            invalid_fields.add("vat")
            error_messages.append(
                _(
                    "Changing VAT number is not allowed once document(s) have been issued for your"
                    " account. Please contact us directly for this operation."
                )
            )

    def _enforce_commercial_field_propagation(
        self, address_values, partner_sudo, invalid_fields, error_messages, **kwargs
    ):
        """Block changes to commercial fields on a sub-address; pop unchanged ones.

        Commercial fields are expected to match the commercial partner's values
        and would be reset if modified on the commercial partner. Sub-addresses
        may not edit them; the form value is either flagged invalid (when
        different) or silently dropped (when identical).
        """
        for commercial_field_name in partner_sudo._commercial_fields():
            if commercial_field_name not in address_values:
                continue
            partner_sudo_field = partner_sudo._fields[commercial_field_name]
            # Cast the stored value to its cache form (ids for relational fields)
            # so it can be compared to the website form values, which are already
            # cache values; comparing a recordset to an id otherwise raises.
            partner_sudo_value = partner_sudo_field.convert_to_cache(
                partner_sudo[commercial_field_name],
                partner_sudo,
            )
            if partner_sudo_value != address_values[commercial_field_name] and (
                bool(partner_sudo_value) or bool(address_values[commercial_field_name])
            ):
                invalid_fields.add(commercial_field_name)
                field_description = partner_sudo_field._description_string(request.env)
                if partner_sudo.commercial_partner_id.is_company:
                    error_messages.append(
                        _(
                            "The %(field_name)s is managed on your company account.",
                            field_name=field_description,
                        )
                    )
                else:
                    error_messages.append(
                        _(
                            "The %(field_name)s is managed on your main account address.",
                            field_name=field_description,
                        )
                    )
            else:
                address_values.pop(commercial_field_name, None)

        # Company name shouldn't be updated anywhere but the main and company address, even
        # if it's not in the fields returned by _commercial_fields.
        if partner_sudo != request.env["res.partner"]._get_current_partner(**kwargs):
            address_values.pop("company_name", None)

    def _validate_address_email_format(
        self, address_values, invalid_fields, error_messages
    ):
        """Validate that ``email`` is a syntactically valid address."""
        if address_values.get("email") and not single_email_re.match(
            address_values["email"]
        ):
            invalid_fields.add("email")
            error_messages.append(
                _("Invalid Email! Please enter a valid email address.")
            )

    def _validate_address_vat_format(
        self, address_values, invalid_fields, error_messages
    ):
        """Validate the VAT number via ``res.partner._check_vat`` when available.

        ``_check_vat`` is provided by the ``account`` module; when account is not
        installed (rare on a customer portal), the check silently no-ops.
        Skipped when ``vat`` is already flagged invalid by an earlier phase.
        """
        ResPartnerSudo = request.env["res.partner"].sudo()
        if (
            address_values.get("vat")
            and hasattr(ResPartnerSudo, "_check_vat")
            and "vat" not in invalid_fields
        ):
            partner_dummy = ResPartnerSudo.new(
                {
                    fname: address_values[fname]
                    for fname in self._get_vat_validation_fields()
                    if fname in address_values
                }
            )
            try:
                partner_dummy._check_vat()
            except ValidationError as exception:
                invalid_fields.add("vat")
                error_messages.append(exception.args[0])

    def _validate_address_required_fields(
        self,
        address_values,
        address_type,
        use_delivery_as_billing,
        required_fields,
        is_commercial_address,
        missing_fields,
        error_messages,
    ):
        """Compute the required-field set for this submission and check the form.

        :param str required_fields: form-level extra required fields, comma-separated.
        :param bool is_commercial_address: when False, commercial fields are not
                                           required (they live on the parent).
        """
        required_field_set = {f for f in required_fields.split(",") if f}

        country_id = address_values.get("country_id")
        country = request.env["res.country"].browse(country_id)
        if address_type == "delivery" or use_delivery_as_billing:
            required_field_set |= self._get_mandatory_delivery_address_fields(country)
        if address_type == "billing" or use_delivery_as_billing:
            required_field_set |= self._get_mandatory_billing_address_fields(country)
            if not is_commercial_address:
                commercial_fields = (
                    request.env["res.partner"].sudo()._commercial_fields()
                )
                for fname in commercial_fields:
                    if fname in required_field_set and fname not in address_values:
                        required_field_set.remove(fname)

        address_fields = self._get_mandatory_address_fields(country)
        if any(address_values.get(fname) for fname in address_fields):
            # If the customer provided any address information, they should provide their whole
            # address, even if the address wasn't required (e.g. the order only contains services).
            required_field_set |= address_fields

        for field_name in required_field_set:
            if not address_values.get(field_name):
                missing_fields.add(field_name)
        if missing_fields:
            error_messages.append(_("Some required fields are empty."))

    def _get_vat_validation_fields(self):
        return {"country_id", "vat"}

    def _complete_address_values(
        self, address_values, address_type, use_delivery_as_billing, **kwargs
    ):
        """Complete the address values with the request's contextual values.

        :param dict address_values: The address values to complete.
        :param str address_type: The type of the address: 'billing' or 'delivery'.
        :param bool use_delivery_as_billing: Whether the provided address should be used as both the
                                             billing and the delivery address.
        :params **kwargs: Other contextual values.
        :return: None
        """
        address_values["lang"] = request.lang.code
        partner = request.env["res.partner"]._get_current_partner(**kwargs)
        address_values["company_id"] = partner.company_id.id
        commercial_partner = partner.commercial_partner_id
        if use_delivery_as_billing:
            address_values["type"] = "other"
        elif address_type == "billing":
            address_values["type"] = "invoice"
        elif address_type == "delivery":
            address_values["type"] = "delivery"

        # Avoid linking the address to the default archived 'Public user' partner.
        if commercial_partner.active:
            address_values["parent_id"] = commercial_partner.id

    def _are_same_addresses(self, address_values, partner):
        ResPartner = request.env["res.partner"]
        for key, new_val in address_values.items():
            val = ResPartner._fields[key].convert_to_cache(partner[key], ResPartner)
            if new_val != val and (val or new_val):
                # Skip falsy values if unset in values and on record
                return False
        return True

    def _handle_extra_form_data(self, extra_form_data, address_values):
        """Hook for handling form fields not mapped to ``res.partner``.

        Default implementation is a no-op. Subclasses may persist these fields
        on related records, fire downstream actions, or merge them back into
        ``address_values``.

        :param dict extra_form_data: Form fields not on ``res.partner`` (e.g.
                                     custom checkout fields from sale or event).
        :param dict address_values: Address values about to be saved.
        """

    @route(
        '/my/address/country_info/<model("res.country"):country>',
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        website=True,
        readonly=True,
    )
    def portal_address_country_info(self, country, address_type, **kw):
        address_fields = country.get_address_fields()
        if address_type == "billing":
            required_fields = self._get_mandatory_billing_address_fields(country)
        else:
            required_fields = self._get_mandatory_delivery_address_fields(country)
        return {
            "fields": address_fields,
            "zip_before_city": (
                "zip" in address_fields
                and address_fields.index("zip") < address_fields.index("city")
            ),
            "states": [(st.id, st.name, st.code) for st in country.sudo().state_ids],
            # Consumed by address.js: a state-mandatory country with no defined
            # states must still show (and require) the state input rather than
            # hiding a required control the user cannot fill.
            "state_required": country.state_required,
            "phone_code": country.phone_code,
            "required_fields": list(required_fields),
        }

    @route(
        "/my/address/archive",
        type="jsonrpc",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def address_archive(self, partner_id):
        address_sudo = (
            request.env["res.partner"]
            .sudo()
            .browse(_parse_record_id(partner_id))
            .exists()
        )
        if not address_sudo or not address_sudo._can_be_edited_by_current_customer():
            raise Forbidden

        if address_sudo == request.env.user.partner_id:
            raise UserError(_("You cannot archive your main address"))

        address_sudo.action_archive()

    # Security

    @route(
        "/my/security", type="http", auth="user", website=True, methods=["GET", "POST"]
    )
    def security(self, **post):
        values = self._prepare_security_rendering_values()

        if request.httprequest.method == "POST":
            # ``_as_password_field``: a hand-crafted POST may omit any of the
            # three fields, and may send one as a *file* part rather than text
            # -- werkzeug then hands over a ``FileStorage``, whose ``.strip()``
            # is an ``AttributeError`` (HTTP 500 on the security page). Anything
            # that is not text is not a password, so it reads as absent, which
            # the empty-field validation in ``_update_password`` already answers.
            values.update(
                self._update_password(
                    _as_password_field(post.get("old")),
                    _as_password_field(post.get("new1")),
                    _as_password_field(post.get("new2")),
                )
            )

        return request.render(
            "portal.portal_my_security",
            values,
            headers=self._FRAME_OPTIONS_HEADERS,
        )

    def _prepare_security_rendering_values(self):
        """Values shared by every render of ``portal.portal_my_security``.

        Used by both the /my/security page and the failed-deactivation
        re-render, so the template always receives ``allow_api_keys`` &co
        regardless of which route rendered it.
        """
        values = self._prepare_portal_layout_values()
        values["get_error"] = get_error
        values["allow_api_keys"] = bool(
            request.env["ir.config_parameter"].sudo().get_param("portal.allow_api_keys")
        )
        values["open_deactivate_modal"] = False
        return values

    def _update_password(self, old, new1, new2):
        for k, v in [("old", old), ("new1", new1), ("new2", new2)]:
            if not v:
                return {
                    "errors": {
                        "password": {k: _("You cannot leave any password empty.")}
                    }
                }

        if new1 != new2:
            return {
                "errors": {
                    "password": {
                        "new2": _(
                            "The new password and its confirmation must be identical."
                        )
                    }
                }
            }

        try:
            request.env["res.users"].change_password(old, new1)
        except AccessDenied as e:
            msg = e.args[0]
            # Detect the default (no-custom-message) AccessDenied by string match
            # against a freshly-constructed instance. Fragile if AccessDenied's
            # default message ever changes — covered by AccessDenied subclasses
            # raised by 2FA / TOTP modules with their own informative messages.
            if msg == AccessDenied().args[0]:
                msg = _(
                    "The old password you provided is incorrect, your password was not changed."
                )
            return {"errors": {"password": {"old": msg}}}
        except UserError as e:
            return {"errors": {"password": str(e)}}

        # update session token so the user does not get logged out (cache cleared by passwd change)
        new_token = request.env.user._compute_session_token(request.session.sid)
        request.session.session_token = new_token

        return {"success": {"password": True}}

    @route(
        "/my/deactivate_account",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def deactivate_account(self, validation, password, **post):
        values = self._prepare_security_rendering_values()
        values["open_deactivate_modal"] = True
        credential = {
            "login": request.env.user.login,
            "password": password,
            "type": "password",
        }

        if validation != request.env.user.login:
            values["errors"] = {"deactivate": "validation"}
        else:
            try:
                request.env["res.users"]._check_credentials(
                    credential, {"interactive": True}
                )
                request.env.user.sudo()._deactivate_portal_user(**post)
                request.session.logout()
                return request.redirect(
                    f"/web/login?message={quote(_('Account deleted!'), safe='/:')}"
                )
            except AccessDenied:
                values["errors"] = {"deactivate": "password"}
            except UserError as e:
                values["errors"] = {"deactivate": {"other": str(e)}}

        return request.render(
            "portal.portal_my_security",
            values,
            headers=self._FRAME_OPTIONS_HEADERS,
        )

    @route("/portal/attachment/remove", type="jsonrpc", auth="public")
    def attachment_remove(self, attachment_id, access_token=None):
        """Remove the given `attachment_id`, only if it is in a "pending" state.

        The user must have access right on the attachment or provide a valid
        `access_token`.
        """
        try:
            attachment_sudo = self._document_check_access(
                "ir.attachment", int(attachment_id), access_token=access_token
            )
        except AccessError, MissingError, TypeError, ValueError:
            # TypeError/ValueError: non-numeric attachment_id — same client
            # feedback as a missing record, without a 500.
            raise UserError(
                _(
                    "The attachment does not exist or you do not have the rights to access it."
                )
            ) from None

        if (
            attachment_sudo.res_model != "mail.compose.message"
            or attachment_sudo.res_id != 0
        ):
            raise UserError(
                _(
                    "The attachment %s cannot be removed because it is not in a pending state.",
                    attachment_sudo.name,
                )
            )

        if attachment_sudo.env["mail.message"].search_count(
            [("attachment_ids", "in", attachment_sudo.ids)], limit=1
        ):
            raise UserError(
                _(
                    "The attachment %s cannot be removed because it is linked to a message.",
                    attachment_sudo.name,
                )
            )

        return attachment_sudo.unlink()

    # Business Methods

    def _document_check_access(self, model_name, document_id, access_token=None):
        """Check if current user is allowed to access the specified record.

        :param str model_name: model of the requested record
        :param int document_id: id of the requested record
        :param str access_token: record token to check if user isn't allowed to read requested record
        :return: expected record, SUDOED, with SUPERUSER context
        :raise MissingError: record not found in database, might have been deleted
        :raise AccessError: current user isn't allowed to read requested document (and no valid token was given)

        The sudo recordset must carry the SUPERUSER uid, not merely ``su=True``
        on the acting user's uid: since the sudo refactor (upstream 1e6c3bec2c5)
        ``.sudo()`` keeps the current uid, which breaks downstream code that
        re-derives ``self.env.uid`` (e.g. ``stock.quant`` doing
        ``self.with_user(self._uid).check_access(...)`` — a portal user signing
        a ``sale_stock`` quotation would crash). Restores upstream fix
        4d942852c82 (odoo/odoo#35030), accidentally reverted here.

        ``"access_token" in _fields`` is checked before the token comparison:
        the field only exists on models inheriting ``portal.mixin``, and
        ``model_name`` is chosen by the caller. Reaching this helper with a
        token and a plain model (this module's own ``/portal/attachment/remove``
        passes ``ir.attachment``; downstream controllers pass whatever they
        own) otherwise raised ``AttributeError`` from the recordset, masking
        the ``AccessError`` that is the correct answer — a model with no token
        field cannot be unlocked by a token.
        """
        document = request.env[model_name].browse(document_id)
        document_sudo = document.with_user(SUPERUSER_ID).exists()
        if not document_sudo:
            raise MissingError(_("This document does not exist."))
        try:
            document.check_access("read")
        except AccessError:
            stored_token = (
                document_sudo.access_token
                if "access_token" in document_sudo._fields
                else None
            )
            if (
                not access_token
                or not isinstance(access_token, str)
                or not stored_token
                or not consteq(stored_token, access_token)
            ):
                raise
        return document_sudo

    def _get_page_view_values(
        self,
        document,
        access_token,
        values,
        session_history,
        no_breadcrumbs,
        /,
        **kwargs,
    ):
        """Include necessary values for portal chatter & pager setup (see template portal.message_thread).

        :param document: record to display on portal
        :param str access_token: provided document access token
        :param dict values: base dict of values where chatter rendering values should be added
        :param str session_history: key used to store latest records browsed on the portal in the session
        :param bool no_breadcrumbs:
        :return: updated values
        :rtype: dict

        The five leading parameters are **positional-only** (PEP 570). Every
        portal document route ends in this method with its leftover query string
        splatted in as ``**kwargs``::

            # account, sale, project, purchase, helpdesk, sign, ...
            values = self._invoice_get_page_view_values(invoice_sudo, access_token, **kw)
              -> self._get_page_view_values(invoice, access_token, values,
                                            "my_invoices_history", False, **kwargs)

        so a visitor appending ``?values=x`` to any portal document URL used to
        supply a second value for a parameter the caller already passes
        positionally -- ``TypeError: ... got multiple values for argument
        'values'``, an HTTP 500 on ``auth="public"`` routes. Confirmed for all
        of ``document``, ``values``, ``session_history`` and ``no_breadcrumbs``.

        Marking them positional-only makes that impossible by construction: a
        query param of the same name now lands in ``kwargs``, where unknown
        client keys already go and are ignored. This is preferable to filtering
        names at each of the ~10 downstream call sites, because the constraint
        belongs to this signature and cannot drift away from it. Every in-tree
        caller already passes these five positionally, and portal is the only
        module that defines this method.
        """
        values["object"] = document

        if access_token:
            # if no_breadcrumbs = False -> force breadcrumbs even if access_token to `invite` users to register if they click on it
            values["no_breadcrumbs"] = no_breadcrumbs
            values["access_token"] = access_token
            values["token"] = access_token  # for portal chatter

        # Those are used notably whenever the payment form is implied in the portal.
        if kwargs.get("error"):
            values["error"] = kwargs["error"]
        if kwargs.get("warning"):
            values["warning"] = kwargs["warning"]
        if kwargs.get("success"):
            values["success"] = kwargs["success"]
        # Email token for posting messages in portal view with identified author
        if kwargs.get("pid"):
            values["pid"] = kwargs["pid"]
        if kwargs.get("hash"):
            values["hash"] = kwargs["hash"]

        history = request.session.get(session_history, [])
        # Only a token-authenticated visitor needs tokens on the prev/next
        # links; for everyone else minting them is a persisted write performed
        # during a GET, on records other than the one being viewed.
        values.update(
            get_records_pager(history, document, with_token=bool(access_token))
        )

        return values

    def _show_report(self, model, report_type, report_ref, download=False):
        if report_type not in ("html", "pdf", "text"):
            raise UserError(_("Invalid report type: %s", report_type))

        ReportAction = request.env["ir.actions.report"].sudo()

        # ``in _fields`` rather than ``hasattr``: hasattr on a recordset swallows
        # *any* exception the attribute access raises (a failing related-field
        # compute, an AccessError), silently skipping the multi-company guard
        # below instead of surfacing the problem.
        if "company_id" in model._fields:
            if len(model.company_id) > 1:
                raise UserError(_("Multi company reports are not supported."))
            ReportAction = ReportAction.with_company(model.company_id)

        method_name = f"_render_qweb_{report_type}"
        report = getattr(ReportAction, method_name)(
            report_ref, list(model.ids), data={"report_type": report_type}
        )[0]
        headers = self._get_http_headers(model, report_type, report, download)
        return request.make_response(report, headers=list(headers.items()))

    # Content type per report type. ``_show_report`` accepts three, but the
    # header only distinguished pdf from "everything else", so a ``text`` report
    # -- the one ``ir.actions.report`` renders through ``_render_qweb_text`` --
    # was served as ``text/html``. A browser then parses plain text as markup:
    # ``<`` in the content starts a tag, and the document the customer sees is
    # not the one the report produced.
    _REPORT_CONTENT_TYPES = {
        "pdf": "application/pdf",
        "html": "text/html",
        "text": "text/plain",
    }

    def _get_http_headers(self, model, report_type, report, download):
        # ``report`` is bytes for PDFs, str for HTML/text — encode the latter
        # so Content-Length matches the wire byte count, not the char count.
        headers = {
            "Content-Type": self._REPORT_CONTENT_TYPES.get(report_type, "text/html"),
            "Content-Length": (
                len(report)
                if isinstance(report, bytes)
                else len(report.encode("utf-8"))
            ),
        }
        if report_type == "pdf":
            filename = f"{re.sub(r'\W+', '_', model._get_report_base_filename())}.pdf"
            headers["Content-Disposition"] = content_disposition(
                filename, disposition_type="attachment" if download else "inline"
            )
        return headers


def get_error(e, path=""):
    """Recursively dereferences `path` (a period-separated sequence of dict
    keys) in `e` (an error dict or value), returns the final resolution IIF it's
    an str, otherwise returns None
    """
    for k in path.split(".") if path else []:
        if not isinstance(e, dict):
            return None
        e = e.get(k)

    return e if isinstance(e, str) else None
