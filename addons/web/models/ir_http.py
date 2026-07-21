import re
from typing import Any

import odoo
from odoo import api, fields, models
from odoo.http import DEFAULT_LANG, DEFAULT_MAX_CONTENT_LENGTH, request
from odoo.tools import config, ormcache
from odoo.tools.misc import hmac, str2bool

# Debug mode is stored in session and should always be a string.
# It can be activated with an URL query string `debug=<mode>` where mode
# is either:
# - 'tests' to load tests assets
# - 'assets' to load assets non minified
# - any other truthy value to enable simple debug mode (to show some
#   technical feature, to show complete traceback in frontend error..)
# - any falsy value to disable debug mode
#
# You can use any truthy/falsy value from `str2bool` (eg: 'on', 'f'..)
# Multiple debug modes can be activated simultaneously, separated with a
# comma (eg: 'tests, assets').
ALLOWED_DEBUG_MODES = ["", "1", "assets", "tests"]

CRAWLER_USER_AGENTS = (
    "bot",
    "crawl",
    "slurp",
    "spider",
    "curl",
    "wget",
    "facebookexternalhit",
    "whatsapp",
    "trendsmapresolver",
    "pinterest",
    "instagram",
    "google-pagerenderer",
    "preview",
)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def is_a_bot(cls) -> bool:
        user_agent = request.httprequest.user_agent.string.lower()
        # Substring matching benchmarked faster than regexp for this use case
        return any(bot in user_agent for bot in CRAWLER_USER_AGENTS)

    @classmethod
    def _sanitize_cookies(cls, cookies: dict) -> None:
        super()._sanitize_cookies(cookies)
        if cids := cookies.get("cids"):
            cookies["cids"] = "-".join(cids.split(","))

    @classmethod
    def _handle_debug(cls) -> None:
        debug = request.httprequest.args.get("debug")
        if debug is not None:
            request.session.debug = ",".join(
                (
                    mode
                    if mode in ALLOWED_DEBUG_MODES
                    else "1"
                    if str2bool(mode, mode)
                    else ""
                )
                for mode in (debug or "").split(",")
            )

    @classmethod
    def _pre_dispatch(cls, rule: Any, args: dict) -> None:
        super()._pre_dispatch(rule, args)
        cls._handle_debug()

    @classmethod
    def _post_logout(cls) -> None:
        super()._post_logout()
        request.future_response.set_cookie("cids", max_age=0)
        request.future_response.set_cookie("content_density", max_age=0)

    def webclient_rendering_context(self) -> dict[str, Any]:
        return {
            "color_scheme": self.color_scheme(),
            "content_density": self.content_density(),
            "session_info": self.session_info(),
        }

    def color_scheme(self) -> str:
        """Return the color scheme for the web client. Override to support dark/system."""
        return "light"

    def content_density(self) -> str:
        """Determine content density for the current request.

        Priority: cookie > user setting > 'default'.
        """
        cookie_density = request.httprequest.cookies.get("content_density")
        if cookie_density in ("compact", "condensed"):
            return cookie_density
        if not request.env.user._is_public():
            density = request.env.user.res_users_settings_id.density
            if density in ("compact", "condensed"):
                return density
        return "default"

    @api.model
    def lazy_session_info(self) -> dict[str, Any]:
        """Return session fields that can be loaded lazily after page render.

        Fields returned here are fetched via a single
        ``orm.call("ir.http", "lazy_session_info")`` RPC issued by the
        ``lazy_session`` JS service after ``WEB_CLIENT_READY`` fires.  Use
        this for data whose absence during boot does not degrade first
        paint (debug tooling, effect flags, action-specific limits) —
        anything read by a service at ``start()`` belongs in
        :meth:`_base_session_info` instead.
        """
        return {
            # Profiling state — consumed by ``@web/webclient/debug/profiling/profiling_service``
            # which only activates in debug mode.  Null defaults fall back to ``false`` /
            # the collector list defined JS-side.
            "profile_session": request.session.get("profile_session"),
            "profile_collectors": request.session.get("profile_collectors"),
            "profile_params": request.session.get("profile_params"),
        }

    def _base_session_info(self) -> dict[str, Any]:
        """Build the session fields shared by both backend and frontend.

        Returns identity/permission flags, registry hash, currencies,
        feature flags, CWV sample rate, and bundle params (lang, debug).
        Both ``session_info`` and ``get_frontend_session_info`` extend
        this base; profiling data is fetched separately via
        ``lazy_session_info``, and config-parameter-driven limits are
        added only by ``session_info`` (backend-only).
        """
        user = self.env.user
        session_uid = request.session.uid
        ir_config_sudo = self.env["ir.config_parameter"].sudo()

        # ``web.cwv.sample_rate`` controls the share of sessions that emit
        # Core Web Vitals beacons.  Default 1.0 (capture all) for dev; lower
        # in prod (e.g. 0.1 = 10%) to bound traffic to /web/observability/cwv
        # and ``web.cwv.metric`` row volume.  Decision is per-session; the
        # JS service samples once at start, not per beacon.
        try:
            cwv_sample_rate = float(
                ir_config_sudo.get_param("web.cwv.sample_rate", default="1.0"),
            )
        except ValueError, TypeError:
            cwv_sample_rate = 1.0
        cwv_sample_rate = max(0.0, min(1.0, cwv_sample_rate))

        info = {
            "uid": session_uid,
            "is_system": user._is_system() if session_uid else False,
            "is_admin": user._is_admin() if session_uid else False,
            "is_public": user._is_public(),
            "is_internal_user": user._is_internal(),
            "registry_hash": hmac(
                self.env(su=True),
                "webclient-cache",
                self.env.registry.registry_sequence,
            ),
            "show_effect": bool(ir_config_sudo.get_param("base.show_effect")),
            "currencies": self.env["res.currency"].get_all_currencies(),
            "quick_login": str2bool(
                ir_config_sudo.get_param("web.quick_login", default=True), True
            ),
            "bundle_params": {
                "lang": request.session.context.get("lang", DEFAULT_LANG),
            },
            "test_mode": config["test_enable"],
            "cwv_sample_rate": cwv_sample_rate,
            "feature_flags": self._resolve_feature_flags(ir_config_sudo),
        }
        if request.session.debug:
            info["bundle_params"]["debug"] = request.session.debug
        if session_uid:
            version_info = odoo.service.common.exp_version()
            info["server_version"] = version_info.get("server_version")
            info["server_version_info"] = version_info.get("server_version_info")
        return info

    _FEATURE_FLAG_PREFIX = "web.feature."

    def _resolve_feature_flags(self, ir_config_sudo: Any = None) -> dict[str, Any]:
        """Collect deployment-wide feature flags into a name -> typed-value dict.

        Reads every ``ir.config_parameter`` row whose key starts with
        ``web.feature.``, strips the prefix, and parses the raw value
        with the same literal-set the JS resolver uses
        (``services/feature_flags.js:_parseValue``): ``true`` / ``false``
        / ``null`` literals, signed integers, floats, otherwise the
        original string.  An empty dict is a valid return value — the
        JS side falls through to call-site defaults when no key matches.

        The underlying lookup is cached per registry (see
        :meth:`_resolve_feature_flags_cached`); a fresh dict is built on
        every call so callers can never mutate the cached value.

        :param ir_config_sudo: unused; kept so existing call sites passing the
            sudoed ``ir.config_parameter`` recordset keep working. The cached
            helper builds its own recordset — the cache key must not depend on
            any caller-supplied recordset/env state.
        :return: dict suitable for inclusion in session_info
        :rtype: dict[str, Any]
        """
        return dict(self._resolve_feature_flags_cached())

    # INVALIDATION CONTRACT: this cache MUST live in the "stable" cache group.
    # ir.config_parameter's create()/write()/unlink() invalidate exactly that
    # group (``self.env.registry.clear_cache("stable")`` — same group as its
    # own ``_get_param`` ormcache), and clear_cache signals the invalidation
    # to every other worker on commit. Any other group would leave stale flags
    # served after a ``web.feature.*`` parameter changes (worst on multi-worker
    # deployments, where only the writing worker would ever notice).
    # The cached method deliberately takes NO arguments: the flag set is
    # deployment-wide (independent of uid/context/companies), so the cache key
    # is just the registry + method.
    @ormcache(cache="stable")
    def _resolve_feature_flags_cached(self) -> tuple[tuple[str, Any], ...]:
        """Return ``((name, parsed_value), ...)`` for every ``web.feature.*``
        parameter. Returns an immutable tuple so a cache hit can be shared
        safely; :meth:`_resolve_feature_flags` wraps it in a fresh dict."""
        rows = (
            self.env["ir.config_parameter"]
            .sudo()
            .search_fetch(
                [("key", "=like", self._FEATURE_FLAG_PREFIX + "%")],
                ["key", "value"],
            )
        )
        prefix_len = len(self._FEATURE_FLAG_PREFIX)
        return tuple(
            (row.key[prefix_len:], self._parse_feature_flag_value(row.value))
            for row in rows
        )

    # Numeric pattern intentionally mirrors the JS regex in
    # ``feature_flags.js:_parseValue`` exactly: signed integer or decimal,
    # NO scientific notation, NO inf/nan.  Python's float() would accept
    # ``1.5e2`` / ``inf`` / ``nan`` and ``Number()`` in JS would too, but
    # the JS regex gate blocks them — we replicate that gate here so a
    # value set via ir.config_parameter resolves to the same type as the
    # same string set via URL or localStorage.
    _NUMERIC_RE = re.compile(r"^-?(\d+\.?\d*|\.\d+)$")

    @classmethod
    def _parse_feature_flag_value(cls, raw: str) -> Any:
        """Parse an ``ir.config_parameter`` value into a JS-compatible type.

        Mirrors ``services/feature_flags.js:_parseValue`` so a flag read
        from URL / localStorage / server resolves to the same JS type
        regardless of source.  Unparseable input is returned as the
        original string, matching the JS fall-through.
        """
        if raw == "true":
            return True
        if raw == "false":
            return False
        if raw == "null":
            return None
        trimmed = raw.strip() if raw else ""
        if not trimmed:
            return True  # bare ``name:`` was treated as truthy on the JS side
        if not cls._NUMERIC_RE.match(trimmed):
            return raw
        # Integer fast-path so ``1`` stays int not 1.0; the regex above
        # already guarantees one of int() / float() succeeds.
        if "." in trimmed:
            return float(trimmed)
        return int(trimmed)

    def _get_config_limits(self, ir_config_sudo: Any) -> dict[str, int]:
        """Read numeric config parameters with safe fallbacks.

        :param ir_config_sudo: sudoed ``ir.config_parameter`` model
        """
        try:
            max_file_upload_size = int(
                ir_config_sudo.get_param(
                    "web.max_file_upload_size",
                    default=DEFAULT_MAX_CONTENT_LENGTH,
                )
            )
        except ValueError, TypeError:
            max_file_upload_size = DEFAULT_MAX_CONTENT_LENGTH
        try:
            active_ids_limit = int(
                ir_config_sudo.get_param("web.active_ids_limit", default="20000")
            )
        except ValueError, TypeError:
            active_ids_limit = 20000
        return {
            "max_file_upload_size": max_file_upload_size,
            "active_ids_limit": active_ids_limit,
        }

    def _get_user_companies_info(self) -> dict[str, Any]:
        """Build the multi-company hierarchy dict for internal users.

        Browses with ``prefetch_fields=False`` so each field accessed
        below (``name``, ``sequence``, ...) is fetched on its own instead
        of pulling every stored field of ``res.company`` into cache.
        """
        user = self.env.user
        user_companies = (
            self.env(context=dict(self.env.context, prefetch_fields=False))[
                "res.company"
            ]
            .browse(user._get_company_ids())
            .sudo()
        )
        disallowed_ancestors = user_companies.parent_ids - user_companies
        full_hierarchy = disallowed_ancestors + user_companies

        # Pre-compute visible IDs and each company's filtered child_ids
        # in one pass, avoiding N recordset intersections below.
        hierarchy_ids = set(full_hierarchy._ids)
        children_in_hierarchy = {
            comp.id: [cid for cid in comp.child_ids._ids if cid in hierarchy_ids]
            for comp in full_hierarchy
        }
        return {
            "current_company": user.company_id.id,
            "allowed_companies": {
                comp.id: {
                    "id": comp.id,
                    "name": comp.name,
                    "sequence": comp.sequence,
                    "child_ids": children_in_hierarchy.get(comp.id, []),
                    "parent_id": comp.parent_id.id,
                    "currency_id": comp.currency_id.id,
                }
                for comp in user_companies
            },
            "disallowed_ancestor_companies": {
                comp.id: {
                    "id": comp.id,
                    "name": comp.name,
                    "sequence": comp.sequence,
                    "child_ids": children_in_hierarchy.get(comp.id, []),
                    "parent_id": comp.parent_id.id,
                }
                for comp in disallowed_ancestors
            },
        }

    def session_info(self) -> dict[str, Any]:
        """Build the full backend session info injected as ``odoo.__session_info__``.

        Extends ``_base_session_info`` with user context, partner data,
        config limits, and multi-company hierarchy for internal users.
        """
        user = self.env.user
        session_uid = request.session.uid

        if session_uid:
            user_context = dict(self.env["res.users"].context_get())
            if user_context != request.session.context:
                request.session.context = user_context
        else:
            user_context = {}

        info = self._base_session_info()
        ir_config_sudo = self.env["ir.config_parameter"].sudo()

        # _base_session_info() already sets the server version, but only for an
        # authenticated session; the backend session_info always exposes it.
        # Fill it in only when absent so exp_version() runs at most once and the
        # two paths can't diverge.
        if "server_version" not in info:
            version_info = odoo.service.common.exp_version()
            info["server_version"] = version_info.get("server_version")
            info["server_version_info"] = version_info.get("server_version_info")

        info.update(
            self._get_config_limits(ir_config_sudo),
            user_context=user_context,
            db=self.env.cr.dbname,
            user_settings=(
                self.env["res.users.settings"]
                ._find_or_create_for_user(user)
                ._res_users_settings_format()
            ),
            support_url="https://www.odoo.com/buy",
            name=user.name,
            username=user.login,
            partner_write_date=fields.Datetime.to_string(user.partner_id.write_date),
            partner_display_name=user.partner_id.display_name,
            partner_id=(
                user.partner_id.id if session_uid and user.partner_id else None
            ),
            home_action_id=user.action_id.id,
            view_info=self.env["ir.ui.view"].get_view_info(),
            groups={
                "base.group_allow_export": (
                    user.has_group("base.group_allow_export") if session_uid else False
                ),
            },
        )
        info["web.base.url"] = ir_config_sudo.get_param("web.base.url", default="")

        if info["is_internal_user"]:
            info["user_companies"] = self._get_user_companies_info()
        return info

    @api.model
    def get_frontend_session_info(self) -> dict[str, Any]:
        """Build the minimal session info for frontend/portal pages.

        Extends ``_base_session_info`` with frontend-specific flags.
        """
        info = self._base_session_info()
        info.update(
            # ``is_website_user`` means "the current user is the public/website
            # visitor" — True precisely for an ANONYMOUS request (no session
            # uid). Gating on ``session_uid`` inverted it (returned False for the
            # public user, contradicting ``is_public`` in the same payload);
            # ``_is_public()`` is already correct for both the authed and
            # anonymous cases. (``website`` overrides this with its own
            # website-scoped notion; this base value serves website-less
            # frontends.)
            is_website_user=self.env.user._is_public(),
            is_frontend=True,
        )
        return info

    @api.deprecated("Deprecated since 19.0, use get_all_currencies on 'res.currency'")
    def get_currencies(self) -> list[dict[str, Any]]:
        return self.env["res.currency"].get_all_currencies()
