# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re
import traceback
import typing
import urllib.parse

import werkzeug.exceptions
import werkzeug.routing
from werkzeug.exceptions import HTTPException, NotFound

from odoo import api, exceptions, http, models, tools
from odoo.exceptions import AccessError, MissingError
from odoo.fields import Domain
from odoo.http import Response, request
from odoo.tools.urls import keep_query

from odoo.addons.base.models import ir_http
from odoo.addons.base.models.ir_http import RequestUID
from odoo.addons.base.models.res_lang import LangData

_logger = logging.getLogger(__name__)

# A slug is an optional "name-" prefix followed by the record id, terminated by
# an end-of-segment marker. The two exported forms below MUST stay equivalent:
#   * _UNSLUG_RE            - capturing, used by _unslug() to pull out (name, id)
#   * _UNSLUG_ROUTE_PATTERN - non-capturing, injected verbatim into werkzeug's
#     route regex by ModelConverter (werkzeug forbids capturing groups / flags).
# Both are built from the same building blocks so they can never drift apart.
_SLUG_NAME = r"\w{1,2}|\w[\w-]+?\w"  # a 1-2 char word, or a word starting & ending on a word char
_SLUG_ID = (
    r"-?\d+"  # the id; '-?' tolerates the negative ids our name pattern can carve out
)
_SLUG_END = r"(?=$|\/|#|\?)"  # lookahead: end of the path segment
_UNSLUG_RE = re.compile(rf"(?:({_SLUG_NAME})-)?({_SLUG_ID}){_SLUG_END}")
_UNSLUG_ROUTE_PATTERN = rf"(?:(?:{_SLUG_NAME})-)?(?:{_SLUG_ID}){_SLUG_END}"


def _lang_base(lang_code: str) -> str:
    """Return the base language of a locale code: "fr_BE" -> "fr",
    "sr@latin" -> "sr", "kab_DZ" -> "kab".
    """
    return lang_code.partition("_")[0].partition("@")[0]


class ModelConverter(ir_http.ModelConverter):
    def __init__(self, url_map, model=False, domain="[]"):
        super().__init__(url_map, model)
        self.domain = domain
        self.regex = _UNSLUG_ROUTE_PATTERN

    def to_python(self, value) -> models.BaseModel:
        record = super().to_python(value)
        if record.id < 0 and not record.exists():
            # limited support for negative IDs due to our slug pattern, assume abs() if not found
            record = record.browse(abs(record.id))
        return record.with_context(_converter_value=value)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    # ------------------------------------------------------------
    # Slug tools
    # ------------------------------------------------------------

    @classmethod
    def _slug(cls, value: models.BaseModel | tuple[int, str]) -> str:
        try:
            identifier, name = value.id, value.display_name
        except AttributeError:
            # assume name_search result tuple
            identifier, name = value
        if not identifier:
            # Wrap ``value`` in a 1-tuple: a bare ``% value`` unpacks a
            # (id, name) tuple as several format args and raises TypeError.
            raise ValueError("Cannot slug non-existent record %r" % (value,))
        slugname = cls._slugify(name or "")
        if not slugname:
            return str(identifier)
        return f"{slugname}-{identifier}"

    @classmethod
    def _unslug(cls, value: str) -> tuple[str | None, int] | tuple[None, None]:
        """Extract slug and id from a string.
        Always return a 2-tuple (str|None, int|None)
        """
        m = _UNSLUG_RE.match(value)
        if not m:
            return None, None
        return m.group(1), int(m.group(2))

    @classmethod
    def _unslug_url(cls, value: str) -> str:
        """From "/blog/my-super-blog-1" to "/blog/1" """
        # str.split() always yields at least one element, so parts[-1] is safe.
        parts = value.split("/")
        slug_id = cls._unslug(parts[-1])[1]
        if slug_id is not None:
            parts[-1] = str(slug_id)
            return "/".join(parts)
        return value

    @classmethod
    def _get_converters(cls) -> dict[str, type]:
        """Get the converters list for custom url pattern werkzeug need to
        match Rule. This override adds the website ones.
        """
        return dict(
            super()._get_converters(),
            model=ModelConverter,
        )

    # ------------------------------------------------------------
    # Language tools
    # ------------------------------------------------------------

    @classmethod
    def _url_localized(
        cls,
        url: str | None = None,
        lang_code: str | None = None,
        canonical_domain: str | None = None,
        prefetch_langs: bool = False,
        force_default_lang: bool = False,
    ) -> str:
        """Returns the given URL adapted for the given lang, meaning that:

        1. It will have the lang suffixed to it
        2. The model converter parts will be translated

        If it is not possible to rebuild a path, use the current one instead.
        :func:`url_quote_plus` is applied on the returned path.

        It will also force the canonical domain if requested.

        >>> _url_localized("/shop/my-phone-14", lang_code="fr_FR")
        '/fr/shop/mon-telephone-14'
        >>> _url_localized(
        ...     "/shop/my-phone-14",
        ...     lang_code="fr_FR",
        ...     canonical_domain="https://example.com",
        ... )
        'https://example.com/fr/shop/mon-telephone-14'
        """
        if not lang_code:
            lang = request.lang
        else:
            lang = request.env["res.lang"]._get_data(code=lang_code)
            if not lang.url_code:
                # An unknown/inactive code makes ``_get_data`` return a dummy
                # LangData whose fields are all ``False``; localizing with it
                # would splice a literal "/False/..." into the path. Fall back
                # to the request's active language instead of emitting garbage.
                lang = request.lang

        if not url:
            qs = keep_query()
            url = request.httprequest.path + ("?%s" % qs if qs else "")

        # '/shop/furn-0269-chaise-de-bureau-noire-17?' to
        # '/shop/furn-0269-chaise-de-bureau-noire-17', otherwise -> 404
        url, sep, qs = url.partition("?")

        try:
            # Re-match the controller where the request path routes.
            rule, args = request.env["ir.http"]._match(url)
            for key, val in list(args.items()):
                if isinstance(val, models.BaseModel):
                    if isinstance(val.env.uid, RequestUID):
                        args[key] = val = val.with_user(request.env.uid)
                    if val.env.context.get("lang") != lang.code:
                        args[key] = val = val.with_context(lang=lang.code)
                    if prefetch_langs:
                        args[key] = val = val.with_context(prefetch_langs=True)
            router = http.root.get_db_router(request.db).bind("")
            path = router.build(rule.endpoint, args)
        except (
            HTTPException,
            AccessError,
            MissingError,
            werkzeug.routing.BuildError,
            ValueError,
        ):
            # Rebuilding the path failed, so fall back to the URL as given. The
            # catch is deliberately wide: the match itself raises any
            # HTTPException -- NotFound, but also MethodNotAllowed (the probe
            # matches with the *current* request's method, e.g. POST, against
            # GET-only rules) and werkzeug's RequestRedirect (a website 308
            # rewrite rule); reading translated ``<model(...)>`` args raises
            # AccessError/MissingError; ``router.build`` raises BuildError when
            # the args no longer satisfy the rule; and the slug builder raises
            # ValueError for a record whose id went falsy (e.g. deleted between
            # match and localize). All mean "cannot rebuild" and must degrade to
            # the URL as given -- never abort the surrounding render with a 3xx,
            # nor 500.
            # ``build`` returns a quoted URL, so quote here too for consistency.
            # Keep "%" safe: the URL may already be percent-quoted (e.g. an
            # href out of a template), and re-quoting would double-encode it
            # ("%C3%A9" -> "%25C3%25A9"). And use ``quote``, not ``quote_plus``:
            # "+" means a space in query strings only, never in a path, where
            # a space must be "%20" (which is also what ``build`` emits).
            path = urllib.parse.quote(url, safe="/%")
        if force_default_lang or lang != request.env["ir.http"]._get_default_lang():
            path = f"/{lang.url_code}{path if path != '/' else ''}"

        if canonical_domain:
            # canonical URLs should not have qs
            return tools.urls.urljoin(canonical_domain, path)

        return path + sep + qs

    @classmethod
    def _url_lang(cls, path_or_uri: str, lang_code: str | None = None) -> str:
        """Given a relative URL, make it absolute and add the required lang or
        remove useless lang.
        Nothing will be done for absolute or invalid URL.
        If there is only one language installed, the lang will not be handled
        unless forced with `lang` parameter.

        :param lang_code: Must be the lang `code`. It could also be something
                          else, such as `'[lang]'` (used for url_return).
        """
        Lang = request.env["res.lang"]
        location = path_or_uri.strip()
        force_lang = lang_code is not None
        try:
            url = urllib.parse.urlparse(location)
        except ValueError:
            # e.g. Invalid IPv6 URL, `urllib.parse.urlparse('http://]')`
            url = False
        # relative URL with either a path or a force_lang
        if url and not url.netloc and not url.scheme and (url.path or force_lang):
            location = urllib.parse.urljoin(request.httprequest.path, location)
            lang_url_codes = [info.url_code for info in Lang._get_frontend().values()]
            lang_code = lang_code or request.env.context["lang"]
            lang_url_code = Lang._get_data(code=lang_code).url_code
            lang_url_code = (
                lang_url_code if lang_url_code in lang_url_codes else lang_code
            )
            if (len(lang_url_codes) > 1 or force_lang) and cls._is_multilang_url(
                location, lang_url_codes
            ):
                loc, sep, qs = location.partition("?")
                ps = loc.split("/")
                default_lg = request.env["ir.http"]._get_default_lang()
                if ps[1] in lang_url_codes:
                    # Replace the language only if we explicitly provide a language to url_for
                    if force_lang:
                        ps[1] = lang_url_code
                    # Remove the default language unless it's explicitly provided
                    elif ps[1] == default_lg.url_code:
                        ps.pop(1)
                # Insert the context language or the provided language
                elif lang_url_code != default_lg.url_code or force_lang:
                    ps.insert(1, lang_url_code)
                    # Remove the last empty string to avoid trailing / after joining
                    if not ps[-1]:
                        ps.pop(-1)

                location = "/".join(ps) + sep + qs
        return location

    @classmethod
    def _url_for(cls, url_from: str, lang_code: str | None = None) -> str:
        """Return the URL adapted for the frontend: here only the lang
        handling of :meth:`_url_lang`; the ``website`` override also applies
        the ``website.rewrite`` rules before delegating here.

        :param url_from: The URL to convert.
        :param lang_code: Must be the lang `code`. It could also be something
                          else, such as `'[lang]'` (used for url_return).
        """
        return cls._url_lang(url_from, lang_code=lang_code)

    @classmethod
    def _is_multilang_url(
        cls, local_url: str, lang_url_codes: list[str] | None = None
    ) -> bool:
        """Check if the given URL content is supposed to be translated.
        To be considered as translatable, the URL should either:
        1. Match a POST (non-GET actually) controller that is `website=True` and
        either `multilang` specified to True or if not specified, with `type='http'`.
        2. If not matching 1., everything not under /static/ or /web/ will be translatable
        """
        if not lang_url_codes:
            lang_url_codes = [
                lg.url_code for lg in request.env["res.lang"]._get_frontend().values()
            ]
        spath = local_url.split("/")
        # if a language is already in the path, remove it (guard the index: a
        # slashless ``local_url`` has no segment [1])
        if len(spath) > 1 and spath[1] in lang_url_codes:
            spath.pop(1)
            local_url = "/".join(spath)

        # Strip the fragment, then the query: only the path routes.
        path = local_url.partition("#")[0].partition("?")[0]

        # Consider /static/ and /web/ files as non-multilang
        if "/static/" in path or path.startswith("/web/"):
            return False

        # Try to match an endpoint in werkzeug's routing table
        try:
            _, func = request.env["ir.http"].url_rewrite(path)

            # /page/xxx has no endpoint/func but is multilang
            return not func or (
                func.routing.get("website", False)
                and func.routing.get("multilang", func.routing["type"] == "http")
            )
        except Exception:
            # Never let a routing-table probe break URL generation: if we
            # cannot decide, treat the URL as non-multilang. Log with context
            # and traceback so the swallowed failure is still diagnosable.
            _logger.warning(
                "Could not determine multilang status for %r, assuming False",
                local_url,
                exc_info=True,
            )
            return False

    @classmethod
    def _get_default_lang(cls) -> LangData:
        lang_code = request.env["ir.default"].sudo()._get("res.partner", "lang")
        if lang_code:
            return request.env["res.lang"]._get_data(code=lang_code)
        return next(iter(request.env["res.lang"]._get_active_by("code").values()))

    @api.model
    def get_frontend_session_info(self) -> dict:
        session_info = super().get_frontend_session_info()

        if request.is_frontend:
            lang = request.lang.code
            session_info["bundle_params"]["lang"] = lang
        session_info.update(
            {
                "translationURL": "/website/translations",
            }
        )
        return session_info

    @api.model
    def get_translation_frontend_modules(self) -> list[str]:
        Modules = request.env["ir.module.module"].sudo()
        extra_modules_name = self._get_translation_frontend_modules_name()
        extra_modules_domain = Domain(self._get_translation_frontend_modules_domain())
        if not extra_modules_domain.is_true():
            new = Modules.search(
                extra_modules_domain & Domain("state", "=", "installed")
            ).mapped("name")
            extra_modules_name += new
        return extra_modules_name

    @classmethod
    def _get_translation_frontend_modules_domain(
        cls,
    ) -> list[tuple[str, str, typing.Any]]:
        """Return a domain to list the domain adding web-translations and
        dynamic resources that may be used frontend views
        """
        return []

    @classmethod
    def _get_translation_frontend_modules_name(cls) -> list[str]:
        """Return a list of module name where web-translations and
        dynamic resources may be used in frontend views
        """
        return ["web"]

    @api.model
    def get_nearest_lang(self, lang_code: str | None) -> str | None:
        """Try to find a similar lang. Eg: fr_BE and fr_FR
        :param lang_code: the lang `code` (en_US)
        :return: a matching frontend lang `code`, or ``None`` if none fits.
        """
        if not lang_code:
            return None

        frontend_langs = self.env["res.lang"]._get_frontend()
        if lang_code in frontend_langs:
            return lang_code

        # Match on the base language: the code up to the territory ("_") or
        # script ("@") qualifier. A plain prefix test is wrong on both sides:
        # it maps ka_GE (Georgian) onto kab_DZ (Kabyle), and fails to map
        # sr@latin onto sr_RS.
        base = _lang_base(lang_code)
        if not base:
            return None
        return next((code for code in frontend_langs if _lang_base(code) == base), None)

    # ------------------------------------------------------------
    # Routing and dispatch
    # ------------------------------------------------------------

    @classmethod
    def _match(cls, path: str) -> tuple[werkzeug.routing.Rule, dict[str, typing.Any]]:
        """
        Grant multilang support to URL matching by using http 3xx
        redirections and URL rewrite. This method also grants various
        attributes such as ``lang`` and ``is_frontend`` on the current
        ``request`` object.

        1/ Use the URL as-is when it matches a non-multilang compatible
           endpoint.

        2/ Use the URL as-is when the lang is not present in the URL and
           that the default lang has been requested.

        3/ Use the URL as-is saving the requested lang when the user is
           a bot and that the lang is missing from the URL.

        4/ Use the url as-is when the lang is missing from the URL, that
           another lang than the default one has been requested but that
           it is forbidden to redirect (e.g. POST)

        5/ Redirect the browser when the lang is missing from the URL
           but another lang than the default one has been requested. The
           requested lang is injected before the original path.

        6/ Redirect the browser when the lang is present in the URL but
           it is the default lang. The lang is removed from the original
           URL.

        7/ Redirect the browser when the lang present in the URL is an
           alias of the preferred lang url code (e.g. fr_FR -> fr)

        8/ Redirect the browser when the requested page is the homepage
           but that there is a trailing slash.

        9/ Rewrite the URL when the lang is present in the URL, that it
           matches and that this lang is not the default one. The URL is
           rewritten to remove the lang.

        Note: The "requested lang" is (in order) either (1) the lang in
              the URL or (2) the lang in the ``frontend_lang`` request
              cookie or (3) the lang in the context or (4) the default
              lang of the website.
        """

        # The URL has been rewritten already
        if hasattr(request, "is_frontend"):
            return super()._match(path)

        # See /1, match a non website endpoint
        matched = None
        try:
            rule, args = cls._match_and_flag(path)
            if not request.is_frontend:
                return rule, args
            matched = (rule, args)
        except NotFound:
            # HTTP-dispatched paths always start with "/" (>=2 segments), but
            # internal callers (e.g. _url_localized) may hand us a slashless or
            # empty path; pad so the unpack degrades to a clean 404 instead of
            # raising ValueError. The padding also guarantees ``rest`` holds at
            # least one element, so ``rest[0]`` is always safe.
            _, url_lang_str, *rest = path.split("/", 2) + ["", ""]
            path_no_lang = "/" + rest[0]
        else:
            url_lang_str = ""
            path_no_lang = path

        allow_redirect = request.httprequest.method != "POST" and getattr(
            request, "is_frontend_multilang", True
        )

        # Some URLs in website are concatenated, first url ends with /,
        # second url starts with /, resulting url contains two following
        # slashes that must be merged. ``re.sub`` collapses any run of
        # slashes in one pass -- a pairwise ``replace("//", "/")`` turns
        # "///" into "//" and needs a second redirect to finish the job.
        if allow_redirect and "//" in path:
            new_url = re.sub(r"/{2,}", "/", path)
            # Carry the query string over: ``redirect`` (unlike ``redirect_query``)
            # drops it, so a bare slash-merge on ``/a//b?x=1`` would silently lose
            # ``?x=1``. Every other branch of this ladder preserves it.
            werkzeug.exceptions.abort(
                request.redirect_query(
                    new_url, request.httprequest.args, code=301, local=True
                )
            )

        default_lang, nearest_url_lang = cls._resolve_frontend_lang(url_lang_str)
        if not nearest_url_lang:
            url_lang_str = None

        # Apply the lang redirect/rewrite ladder (cases /2../9); this either
        # aborts with a 3xx or returns the path to (re)match.
        path = cls._reroute_for_lang(
            path, path_no_lang, url_lang_str, default_lang, allow_redirect
        )

        if matched is not None:
            # The path matched directly, so it carried no lang prefix
            # (``url_lang_str`` is falsy by construction) and the ladder --
            # having not aborted with a redirect above -- necessarily left
            # ``path`` untouched (only case /9 rewrites it, and it needs a
            # lang prefix). Re-matching the same path would repeat the whole
            # werkzeug match plus every converter's ``to_python`` for
            # nothing; reuse the rule found by /1 instead.
            return matched

        # Re-match using rewritten route and really raise for 404 errors
        try:
            return cls._match_and_flag(path)
        except NotFound:
            # Use website to render a nice 404 Not Found html page
            request.is_frontend = True
            request.is_frontend_multilang = True
            raise

    @classmethod
    def _match_and_flag(
        cls, path: str
    ) -> tuple[werkzeug.routing.Rule, dict[str, typing.Any]]:
        """Match ``path`` against the (non-http_routing) routing table and set
        ``request.is_frontend`` / ``request.is_frontend_multilang`` from the
        matched rule. Raises ``NotFound`` like the parent when nothing matches.
        """
        rule, args = super()._match(path)
        routing = rule.endpoint.routing
        request.is_frontend = routing.get("website", False)
        request.is_frontend_multilang = request.is_frontend and routing.get(
            "multilang", routing["type"] == "http"
        )
        return rule, args

    @classmethod
    def _resolve_frontend_lang(cls, url_lang_str: str) -> tuple[LangData, str | None]:
        """Determine and set ``request.lang`` for a frontend request.

        The "requested lang" is, in priority order: the lang in the URL, the
        ``frontend_lang`` cookie, the context lang, then the website default.

        There is no user on the environment yet but resolving the lang reads
        ``res.lang`` / ``ir.default``, so we temporarily grant the public user
        and restore the real env afterwards. Don't try it at home!

        :return: a ``(default_lang, nearest_url_lang)`` tuple. ``nearest_url_lang``
                 is falsy when the URL carried no (recognizable) lang.
        """
        real_env = request.env
        try:
            request.registry["ir.http"]._auth_method_public()  # it calls update_env
            nearest_url_lang = request.env["ir.http"].get_nearest_lang(
                request.env["res.lang"]._get_data(url_code=url_lang_str).code
                or url_lang_str
            )
            cookie_lang = request.env["ir.http"].get_nearest_lang(
                request.cookies.get("frontend_lang")
            )
            context_lang = request.env["ir.http"].get_nearest_lang(
                real_env.context.get("lang")
            )
            default_lang = cls._get_default_lang()
            request.lang = request.env["res.lang"]._get_data(
                code=(
                    nearest_url_lang or cookie_lang or context_lang or default_lang.code
                )
            )
        finally:
            request.env = real_env
        return default_lang, nearest_url_lang

    @classmethod
    def _redirect_lang(cls, target: str, code: int = 303) -> typing.NoReturn:
        """Abort the current request with a lang-aware 3xx redirect.

        Every branch of the redirect ladder shares the same three steps: build
        the redirect (carrying the original query string), pin the
        ``frontend_lang`` cookie to the language the browser is being routed
        to, and abort with it.

        The cookie always records ``request.lang`` -- the destination language
        -- keeping a single invariant across the whole module: the
        ``frontend_lang`` cookie holds the active frontend language. This is
        the same value :meth:`_frontend_pre_dispatch` writes on the request
        that is finally dispatched, so the redirect and its followed request
        agree instead of momentarily disagreeing.

        The default ``code`` mirrors :meth:`request.redirect_query` (303); the
        permanent-move branches pass ``301`` explicitly.
        """
        redirect = request.redirect_query(target, request.httprequest.args, code=code)
        redirect.set_cookie("frontend_lang", request.lang.code)
        werkzeug.exceptions.abort(redirect)

    @classmethod
    def _reroute_for_lang(
        cls,
        path: str,
        path_no_lang: str,
        url_lang_str: str | None,
        default_lang: LangData,
        allow_redirect: bool,
    ) -> str:
        """Apply the multilang redirect/rewrite ladder (cases /2../9 of
        :meth:`_match`), given the already-resolved ``request.lang``.

        Either aborts the request with a 3xx redirect, or returns the path to
        (re)match: the original ``path``, or ``path_no_lang`` when a valid
        non-default lang was stripped from the URL (case /9).
        """
        request_url_code = request.lang.url_code

        # See /2, no lang in url and default website
        if not url_lang_str and request.lang == default_lang:
            _logger.debug(
                "%r (lang: %r) no lang in url and default website, continue",
                path,
                request_url_code,
            )

        # See /3, missing lang in url but user-agent is a bot
        elif not url_lang_str and request.env["ir.http"].is_a_bot():
            _logger.debug(
                "%r (lang: %r) missing lang in url but user-agent is a bot, continue",
                path,
                request_url_code,
            )
            request.lang = default_lang

        # See /4, no lang in url and should not redirect (e.g. POST), continue
        elif not url_lang_str and not allow_redirect:
            _logger.debug(
                "%r (lang: %r) no lang in url and should not redirect (e.g. POST), continue",
                path,
                request_url_code,
            )

        # See /5, missing lang in url, /home -> /fr/home. A bare "/" would
        # yield "/<lang>/", which case /8 would then 301 to "/<lang>" on the
        # next request -- skip the extra hop and target "/<lang>" directly.
        elif not url_lang_str:
            _logger.debug(
                "%r (lang: %r) missing lang in url, redirect", path, request_url_code
            )
            cls._redirect_lang(f"/{request_url_code}{path if path != '/' else ''}")

        # See /6, default lang in url, /en/home -> /home. Here ``request.lang``
        # resolved from ``url_lang_str`` *is* the default lang, so the cookie
        # (always ``request.lang``) correctly records the default.
        elif url_lang_str == default_lang.url_code and allow_redirect:
            _logger.debug(
                "%r (lang: %r) default lang in url, redirect", path, request_url_code
            )
            cls._redirect_lang(path_no_lang)

        # See /7, lang alias in url, /fr_FR/home -> /fr/home. For a bare
        # "/fr_FR", ``path_no_lang`` is "/": target "/fr" directly instead of
        # "/fr/", which case /8 would 301 a second time (same as case /5).
        elif url_lang_str != request_url_code and allow_redirect:
            _logger.debug(
                "%r (lang: %r) lang alias in url, redirect", path, request_url_code
            )
            cls._redirect_lang(
                f"/{request_url_code}{path_no_lang if path_no_lang != '/' else ''}",
                code=301,
            )

        # See /8, homepage with trailing slash. /fr_BE/ -> /fr_BE. The cookie
        # records ``request.lang`` (the URL's non-default lang), not the default
        # -- otherwise a bare /<lang>/ would emit a redirect claiming the wrong
        # frontend_lang.
        elif path == f"/{url_lang_str}/" and allow_redirect:
            _logger.debug(
                "%r (lang: %r) homepage with trailing slash, redirect",
                path,
                request_url_code,
            )
            cls._redirect_lang(path[:-1], code=301)

        # See /9, valid lang in url
        elif url_lang_str == request_url_code:
            # Rewrite the URL to remove the lang
            _logger.debug(
                "%r (lang: %r) valid lang in url, rewrite url and continue",
                path,
                request_url_code,
            )
            request.reroute(path_no_lang)
            path = path_no_lang

        else:
            _logger.warning(
                "%r (lang: %r) couldn't correctly route this frontend request, url used as-is.",
                path,
                request_url_code,
            )

        return path

    @classmethod
    def _pre_dispatch(
        cls, rule: werkzeug.routing.Rule, args: dict[str, typing.Any]
    ) -> None:
        super()._pre_dispatch(rule, args)

        if request.is_frontend:
            cls._frontend_pre_dispatch()

            # update the context of "<model(...):...>" args
            for key, val in list(args.items()):
                if isinstance(val, models.BaseModel):
                    args[key] = val.with_context(request.env.context)

        if request.is_frontend_multilang:
            # A product with id 1 and named 'egg' is accessible via a
            # frontend multilang enpoint 'foo' at the URL '/foo/1'.
            # The preferred URL to access the product (and to generate
            # URLs pointing it) should instead be the sluggified URL
            # '/foo/egg-1'. This code is responsible of redirecting the
            # browser from '/foo/1' to '/foo/egg-1', or '/fr/foo/1' to
            # '/fr/foo/oeuf-1'. While it is nice (for humans) to have a
            # pretty URL, the real reason of this redirection is SEO.
            if request.httprequest.method in ("GET", "HEAD"):
                _, path = rule.build(args)
                assert path is not None
                generated_path = urllib.parse.unquote_plus(path)
                current_path = urllib.parse.unquote_plus(request.httprequest.path)
                if generated_path != current_path:
                    if request.lang != cls._get_default_lang():
                        path = f"/{request.lang.url_code}{path}"
                    redirect = request.redirect_query(
                        path, request.httprequest.args, code=301
                    )
                    werkzeug.exceptions.abort(redirect)

    @classmethod
    def _frontend_pre_dispatch(cls) -> None:
        request.update_context(lang=request.lang.code)
        if request.cookies.get("frontend_lang") != request.lang.code:
            request.future_response.set_cookie("frontend_lang", request.lang.code)

    # ------------------------------------------------------------
    # Exception
    # ------------------------------------------------------------

    @classmethod
    def _get_exception_code_values(
        cls, exception: Exception
    ) -> tuple[int, dict[str, typing.Any]]:
        """Return a tuple with the error code following by the values matching the exception"""
        code = 500  # default code
        values = {
            "exception": exception,
            "traceback": "".join(traceback.format_exception(exception)),
        }

        if isinstance(exception, exceptions.UserError):
            code = exception.http_status
            values["error_message"] = exception.args[0]
        elif isinstance(exception, werkzeug.exceptions.HTTPException):
            code = exception.code
            values["error_message"] = exception.description

        if hasattr(exception, "qweb"):
            values.update(qweb_exception=exception.qweb)
            if code == 404 and exception.qweb.path:
                # If there is a path, it means that the error does not
                # come directly from the called template (for example a
                # "/t" from a t-call MissingError)
                code = 500

        values.update(
            status_message=werkzeug.http.HTTP_STATUS_CODES.get(code, ""),
            status_code=code,
        )

        return (code, values)

    @classmethod
    def _get_values_500_error(cls, env, values, exception):
        values["view"] = env["ir.ui.view"]
        return values

    @classmethod
    def _get_error_html(
        cls, env, code: int, values: dict[str, typing.Any]
    ) -> tuple[int, typing.Any]:
        try:
            return code, env["ir.ui.view"]._render_template(
                "http_routing.%s" % code, values
            )
        except MissingError:
            # ``code`` is an int for every real status, but a bare
            # werkzeug HTTPException carries ``code = None``; guard so the
            # comparison stays a clean re-raise instead of a TypeError.
            if isinstance(code, int) and 400 <= code < 500:
                return code, env["ir.ui.view"]._render_template(
                    "http_routing.4xx", values
                )
            raise

    @classmethod
    def _handle_error(cls, exception):
        response = super()._handle_error(exception)

        is_frontend_request = bool(getattr(request, "is_frontend", False))
        if not is_frontend_request or not isinstance(response, HTTPException):
            # neither handle backend requests nor plain responses
            return response

        # minimal setup to serve frontend pages
        if not request.env.uid:
            cls._auth_method_public()
        cls._handle_debug()
        cls._frontend_pre_dispatch()
        request.params = request.get_http_params()

        code, values = cls._get_exception_code_values(exception)

        request.env.cr.rollback()
        if code in (404, 403):
            try:
                response = cls._serve_fallback()
                if response:
                    cls._post_dispatch(response)
                    return response
            except werkzeug.exceptions.Forbidden:
                # Rendering does raise a Forbidden if target is not visible.
                pass  # Use default error page handling.
        elif code == 500:
            values = cls._get_values_500_error(request.env, values, exception)
        try:
            code, html = cls._get_error_html(request.env, code, values)
        except Exception:
            _logger.exception("Couldn't render a template for http status %s", code)
            # The first attempt may have aborted the PG transaction (e.g. an
            # INSERT into ir_attachment from asset-bundle generation hit a
            # read-only cursor and raised ReadOnlySqlTransaction).  Without
            # an explicit rollback the fallback render's SELECT would fail
            # with "current transaction is aborted, commands ignored", and
            # the user would see the outer 500 instead of the simpler error
            # page this branch is meant to deliver.
            request.env.cr.rollback()
            code, html = (
                418,
                request.env["ir.ui.view"]._render_template(
                    "http_routing.http_error", values
                ),
            )

        response = Response(html, status=code, content_type="text/html;charset=utf-8")
        cls._post_dispatch(response)
        return response

    # ------------------------------------------------------------
    # Rewrite
    # ------------------------------------------------------------

    @api.model
    def _routing_map_key(self) -> int | str | None:
        """Discriminator of the routing map the current request matches
        against. It MUST mirror the ``key`` that :meth:`routing_map` resolves
        when called without one (``website`` overrides both to scope the map
        -- and therefore the :meth:`url_rewrite` cache -- per website).
        """
        return None

    @api.model
    @tools.ormcache("self._routing_map_key()", "path", cache="routing.rewrites")
    def url_rewrite(
        self, path: str, _visited: frozenset[str] = frozenset()
    ) -> tuple[str, typing.Any]:
        """Resolve ``path`` against the routing table.

        Besides the routing-map discriminator, the result only depends on
        ``path``: a redirect rule's target path is built from the rule alone
        (werkzeug appends any query string as a separate URL component, which
        is discarded below), so the query string plays no part in the cache
        key.

        :return: a ``(path, endpoint)`` tuple: the possibly-rewritten path (a
                 redirect rule reports its target) and the endpoint serving it,
                 or ``False`` when nothing matches.
        """
        router = http.root.get_db_router(request.db).bind("")
        try:
            try:
                func, _args = router.match(path, method="POST")
            except werkzeug.exceptions.MethodNotAllowed:
                func, _args = router.match(path, method="GET")
        except werkzeug.routing.RequestRedirect as e:
            # e.new_url is absolute ("http://host/path?qs"); keep only the path.
            # urlsplit is robust to the scheme/host (http vs https, empty host
            # from bind("")) that a hardcoded prefix strip silently mishandles.
            # Recurse to resolve the redirect target's own endpoint, but report
            # the first redirect target as the rewritten path.
            new_path = urllib.parse.urlsplit(e.new_url).path
            if new_path == path or new_path in _visited:
                # A redirect cycle (e.g. two website.rewrite 308 rules mapping
                # /a -> /b and /b -> /a) must not recurse forever: report the
                # path as unroutable instead of killing every render that
                # generates a URL through it with a RecursionError.
                _logger.warning(
                    "Redirect loop while rewriting %r (targets %r again)",
                    path,
                    new_path,
                )
                return path, False
            # ``_visited`` is intentionally absent from the ormcache key: it
            # only breaks in-flight cycles and never changes a loop-free result.
            _, func = self.url_rewrite(new_path, _visited | {path})
            return new_path or path, func
        except werkzeug.exceptions.NotFound:
            return path, False
        return path, func
