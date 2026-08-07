# Part of Odoo. See LICENSE file for full copyright and licensing details.

import contextlib
import logging
import re
import threading
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

# A slug is an optional "name-" prefix, the record id, then an end-of-segment
# marker. Both forms share the building blocks below so they cannot drift:
# _UNSLUG_RE captures (name, id) for _unslug(), while _UNSLUG_ROUTE_PATTERN is
# non-capturing because werkzeug forbids groups in a converter regex.
_SLUG_NAME = r"\w{1,2}|\w[\w-]+?\w"  # a 1-2 char word, or a word starting & ending on a word char
_SLUG_ID = (
    r"-?\d+"  # the id; '-?' tolerates the negative ids our name pattern can carve out
)
_SLUG_END = r"(?=$|\/|#|\?)"  # lookahead: end of the path segment
_UNSLUG_RE = re.compile(rf"(?:({_SLUG_NAME})-)?({_SLUG_ID}){_SLUG_END}")
_UNSLUG_ROUTE_PATTERN = rf"(?:(?:{_SLUG_NAME})-)?(?:{_SLUG_ID}){_SLUG_END}"

# The methods this module may answer with a 3xx. RFC 9110 lets a client turn a
# 301/302 on an unsafe method into a GET (and a 303 mandates it), so redirecting
# anything else drops the body and the intended method. OPTIONS is dropped from
# ``SAFE_HTTP_METHODS`` too: a CORS preflight is never followed through a 3xx.
_REDIRECTABLE_METHODS = ("GET", "HEAD")


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
        """Extract the name and id from a slug.

        :return: ``(name, id)`` -- ``name`` is ``None`` for a bare id, and the
                 whole tuple is ``(None, None)`` when ``value`` is not a slug.
        """
        m = _UNSLUG_RE.match(value)
        if not m:
            return None, None
        return m.group(1), int(m.group(2))

    @classmethod
    def _unslug_url(cls, value: str) -> str:
        """From "/blog/my-super-blog-1" to "/blog/1".

        Only the last *path* segment is reduced; a query string and/or a
        fragment ride along untouched ("/blog/my-blog-1?p=2" -> "/blog/1?p=2").
        """
        # Cut the query/fragment off first: ``_unslug`` accepts "?" and "#" as
        # segment terminators, so the last ``split("/")`` chunk unslugs fine --
        # but replacing it wholesale would take "?page=2" down with the slug.
        cut = min(
            (i for i in (value.find("?"), value.find("#")) if i != -1),
            default=len(value),
        )
        path, suffix = value[:cut], value[cut:]
        # str.split() always yields at least one element, so parts[-1] is safe.
        parts = path.split("/")
        slug_id = cls._unslug(parts[-1])[1]
        if slug_id is None:
            return value
        parts[-1] = str(slug_id)
        return "/".join(parts) + suffix

    @classmethod
    def _get_converters(cls) -> dict[str, type]:
        """Return the converters werkzeug uses to match a Rule.

        Replaces base's ``model`` converter with the slug-aware one above.
        """
        return dict(
            super()._get_converters(),
            model=ModelConverter,
        )

    # ------------------------------------------------------------
    # Language tools
    # ------------------------------------------------------------

    @classmethod
    def _lang_url_prefix(cls, path: str, url_code: str) -> str:
        """Prefix a root-relative ``path`` with a language's ``url_code``.

        "/shop" -> "/fr/shop", and a bare "/" -> "/fr" (not "/fr/", which case
        /8 of the ladder would then 301 away, costing an extra round trip). A
        ``path`` that is not root-relative is repaired, with a warning.
        """
        if not path.startswith("/"):
            # Callers are expected to pass a path; be loud in tests rather than
            # silently emit "/frx", but still degrade to something well-formed.
            _logger.warning("Lang-prefixing a non root-relative path %r", path)
            path = "/" + path
        return f"/{url_code}{path if path != '/' else ''}"

    @classmethod
    def _url_localized(
        cls,
        url: str | None = None,
        lang_code: str | None = None,
        canonical_domain: str | None = None,
        prefetch_langs: bool = False,
        force_default_lang: bool = False,
    ) -> str:
        """Return ``url`` adapted for ``lang_code``: prefixed with that
        language's ``url_code``, with its ``<model(...)>`` segments re-slugged in
        it ("/shop/my-phone-14" -> "/fr/shop/mon-telephone-14"). A URL that is
        not root-relative comes back untouched, and a path that cannot be
        rebuilt degrades to the one given. ``canonical_domain``, if set, is
        joined onto the result, which then carries no query string.

        :param prefetch_langs: set ``prefetch_langs`` on the ``<model(...)>``
                               records matched in the URL.
        :param force_default_lang: prefix the URL even when the target language
                                   is the default one.
        """
        # Guard non-local URLs, mirroring :meth:`_url_lang`: an absolute,
        # protocol-relative ("//cdn/x.png") or non-http ("mailto:", "#anchor")
        # URL would otherwise be percent-quoted *as a path* and lang-prefixed
        # ("https://odoo.com/shop" -> "/frhttps%3A//odoo.com/shop"). A falsy
        # ``url`` still means "derive the path from the request", further down.
        if url and (not url.startswith("/") or url.startswith("//")):
            return url

        if not lang_code:
            lang = request.lang
        else:
            lang = request.env["res.lang"]._get_data(code=lang_code)
            if not lang.url_code:
                # An unknown/inactive code yields a dummy LangData whose fields
                # are all ``False``, which would splice a literal "/False/..."
                # into the path; fall back to the request's language.
                lang = request.lang

        if not url:
            qs = keep_query()
            url = request.httprequest.path + ("?%s" % qs if qs else "")

        # '/shop/furn-0269-chaise-de-bureau-noire-17?' to
        # '/shop/furn-0269-chaise-de-bureau-noire-17', otherwise -> 404
        url, sep, qs = url.partition("?")

        try:
            # Match the routing map directly, never ``ir.http._match``: that is
            # the dispatch entry point and it mutates the live request (it
            # stamps ``is_frontend``/``lang``, and case /9 reroutes the request
            # being served). A URL-generation helper must observe the routing
            # table, never steer it.
            rule, args = (
                request.env["ir.http"]
                .routing_map()
                .bind_to_environ(request.httprequest.environ)
                .match(path_info=url, return_rule=True)
            )
            for key, val in list(args.items()):
                if isinstance(val, models.BaseModel):
                    if isinstance(val.env.uid, RequestUID):
                        args[key] = val = val.with_user(request.env.uid)
                    if val.env.context.get("lang") != lang.code:
                        args[key] = val = val.with_context(lang=lang.code)
                    if prefetch_langs:
                        args[key] = val = val.with_context(prefetch_langs=True)
            router = http.root.get_db_router(request.db, env=request.env).bind("")
            path = router.build(rule.endpoint, args)
        except (
            HTTPException,
            AccessError,
            MissingError,
            werkzeug.routing.BuildError,
            ValueError,
        ):
            # Every listed exception means "cannot rebuild" -- the probe matches
            # with the request's own method (MethodNotAllowed), honours 308
            # rewrite rules (RequestRedirect) and reads live records for
            # translated ``<model(...)>`` args -- so degrade to the URL as given
            # instead of aborting the surrounding render. Quote as ``build``
            # would, keeping "%" safe so an already-quoted href is not
            # double-encoded; "+" is not a path space, hence not ``quote_plus``.
            path = urllib.parse.quote(url, safe="/%")
        if force_default_lang or lang != request.env["ir.http"]._get_default_lang():
            path = cls._lang_url_prefix(path, lang.url_code)

        if canonical_domain:
            # canonical URLs should not have qs
            return tools.urls.urljoin(canonical_domain, path)

        return path + sep + qs

    @classmethod
    def _url_lang(cls, path_or_uri: str, lang_code: str | None = None) -> str:
        """Make a relative URL absolute and add or strip its lang prefix.

        An absolute or invalid URL comes back untouched. With a single installed
        language the prefix is left alone unless ``lang_code`` forces it.

        :param lang_code: the lang ``code``, or a placeholder such as
                          ``'[lang]'`` (used for url_return).
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
            # The context lang is not guaranteed (``with_context(lang=None)``),
            # and a non-string would be spliced straight into the path below.
            # Fall back to the request's lang, then the frontend default.
            if not lang_code:
                lang_code = request.env.context.get("lang") or getattr(
                    getattr(request, "lang", None), "code", None
                )
            lang_url_code = (
                Lang._get_data(code=lang_code).url_code if lang_code else None
            )
            # An unrecognized ``lang_code`` is passed through verbatim on
            # purpose: ``'[lang]'`` is a placeholder url_return substitutes
            # later. It must still be a string to be joined into a path.
            if lang_url_code not in lang_url_codes:
                lang_url_code = lang_code if isinstance(lang_code, str) else None
            if lang_url_code is None:
                lang_url_code = request.env["ir.http"]._get_default_lang().url_code
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
        """Whether the content served at ``local_url`` is translated.

        ``/static/`` and ``/web/`` paths never are. Any other path is, unless it
        resolves to an endpoint that is not ``website=True``, or whose
        ``multilang`` (defaulting to ``type == 'http'``) is false. A path
        matching no endpoint at all is translatable.
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

    @api.model
    @tools.ormcache()
    def _get_default_lang_code(self) -> str | None:
        """Return the configured frontend default language code, or ``None``."""
        # ``ir.default._get`` searches ``ir_default`` uncached, and this sits on
        # the URL-building hot path (once per generated link). Both dependencies
        # invalidate the ``default`` container: ``ir.default`` writes call
        # ``registry.clear_cache()`` and ``res.lang`` writes call
        # ``clear_cache("stable")``, which covers "default" per ``CACHES_BY_KEY``.
        return self.env["ir.default"].sudo()._get("res.partner", "lang")

    @api.model
    def _get_default_lang(self) -> LangData:
        """Return the frontend default language, always an active one.

        A stale ``ir.default`` row (nothing validates it) makes ``_get_data``
        answer with a dummy LangData equal to no real language, which inverts
        the site's canonical URLs: case /2 stops matching so case /5 prefixes
        "/foo", and case /6 stops stripping "/en". Fall back to the first active
        language instead.
        """
        Lang = self.env["res.lang"]
        lang_code = self.env["ir.http"]._get_default_lang_code()
        lang = Lang._get_data(code=lang_code) if lang_code else None
        if not lang:  # LangData.__bool__ is bool(self.id): a dummy is falsy
            lang = next(iter(Lang._get_active_by("code").values()))
        return lang

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
        """Return a domain selecting the modules whose web translations and
        dynamic resources may be used in frontend views.
        """
        return []

    @classmethod
    def _get_translation_frontend_modules_name(cls) -> list[str]:
        """Return the module names whose web translations and dynamic resources
        may be used in frontend views.
        """
        return ["web"]

    @api.model
    def get_nearest_lang(self, lang_code: str | None) -> str | None:
        """Return a frontend lang similar to ``lang_code`` (e.g. fr_BE -> fr_FR).

        :param lang_code: the lang ``code`` (e.g. "en_US")
        :return: a matching frontend lang ``code``, or ``None`` if none fits.
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

        1/ Use the URL as-is when it matches a non-frontend endpoint (one
           whose route is not ``website=True``).

        2/ Use the URL as-is when the lang is not present in the URL and
           that the default lang has been requested.

        3/ Use the URL as-is, forcing the default lang, when the lang is
           missing from the URL and the user-agent is a bot.

        4/ Use the url as-is when the lang is missing from the URL, that
           another lang than the default one has been requested but that
           it is forbidden to redirect (i.e. any method outside
           ``_REDIRECTABLE_METHODS``, e.g. POST)

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
           rewritten to remove the lang. This also catches the aliases
           cases /6 and /7 would have redirected when redirecting is
           forbidden: the request is then served in the URL's language
           rather than 404ing on the un-stripped prefix.

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
            # internal callers (``website.menu`` probes a raw menu url) may pass
            # a slashless or empty path; the padding keeps the unpack and
            # ``rest[0]`` safe, degrading to a clean 404 instead of ValueError.
            _, url_lang_str, *rest = path.split("/", 2) + ["", ""]
            path_no_lang = "/" + rest[0]
        else:
            url_lang_str = ""
            path_no_lang = path

        allow_redirect = (
            request.httprequest.method in _REDIRECTABLE_METHODS
            and getattr(request, "is_frontend_multilang", True)
        )

        # Concatenated website URLs (".../" + "/...") leave a double slash to merge.
        # ``re.sub`` collapses a whole run in one pass, where a pairwise
        # ``replace("//", "/")`` would need a second redirect for "///".
        if allow_redirect and "//" in path:
            new_url = re.sub(r"/{2,}", "/", path)
            # ``redirect_query``, not ``redirect`` (which drops the query
            # string), so a slash-merge on ``/a//b?x=1`` keeps ``?x=1``.
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
            # A direct match carried no lang prefix, so the ladder -- having not
            # redirected above -- left ``path`` untouched (only case /9 rewrites
            # it, and it needs a prefix). Reuse /1's rule instead of repeating
            # the werkzeug match and every converter's ``to_python``.
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
        """Match ``path`` through ``super()._match`` and set
        ``request.is_frontend`` / ``request.is_frontend_multilang`` from the
        matched rule.

        :raises NotFound: when nothing matches, as the parent does.
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

        The requested lang is, in priority order: the lang in the URL, the
        ``frontend_lang`` cookie, the context lang, then the website default.

        :return: ``(default_lang, nearest_url_lang)``; ``nearest_url_lang`` is
                 falsy when the URL carried no recognizable lang.
        """
        with cls._borrowed_public_env() as real_env:
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
            default_lang = request.env["ir.http"]._get_default_lang()
            request.lang = request.env["res.lang"]._get_data(
                code=(
                    nearest_url_lang or cookie_lang or context_lang or default_lang.code
                )
            )
        return default_lang, nearest_url_lang

    @classmethod
    @contextlib.contextmanager
    def _borrowed_public_env(cls) -> typing.Iterator[api.Environment]:
        """Temporarily grant the public user, yielding the *real* environment.

        Resolving the frontend lang reads ``res.lang``/``ir.default`` before the
        request is authenticated, so it needs a user.
        """
        # ``_auth_method_public`` goes through ``request.update_env``, which sets
        # three things: ``request.env``, ``transaction.default_env`` and the
        # worker thread's ``uid``. Restore all three -- ``Transaction.flush``
        # takes its user from ``default_env``, and the thread uid stamps every
        # log line until ``_authenticate`` runs.
        real_env = request.env
        real_default_env = real_env.transaction.default_env
        real_uid = getattr(threading.current_thread(), "uid", None)
        try:
            request.registry["ir.http"]._auth_method_public()  # calls update_env
            yield real_env
        finally:
            request.env = real_env
            real_env.transaction.default_env = real_default_env
            threading.current_thread().uid = real_uid

    @classmethod
    def _redirect_lang(cls, target: str, code: int = 303) -> typing.NoReturn:
        """Abort the request with a 3xx to ``target``, carrying the query string
        and pinning ``frontend_lang`` to the destination language.

        :param code: 303, as :meth:`request.redirect_query` defaults to; the
                     permanent-move branches pass 301.
        """
        # The cookie always records ``request.lang``, the same value
        # :meth:`_frontend_pre_dispatch` writes on the request finally
        # dispatched, so redirect and followed request agree on the language.
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

        Either aborts the request with a 3xx, or returns the path to (re)match:
        ``path`` as given, or ``path_no_lang`` when case /9 stripped a valid
        lang. The trailing ``else`` is unreachable defence -- case /9 closes
        both the redirectable and the non-redirectable branch.
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
            cls._redirect_lang(cls._lang_url_prefix(path, request_url_code))

        # See /6, default lang in url, /en/home -> /home. ``request.lang``
        # resolved from ``url_lang_str`` *is* the default here, so the cookie
        # correctly records the default.
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
                cls._lang_url_prefix(path_no_lang, request_url_code), code=301
            )

        # See /8, homepage with trailing slash. /fr_BE/ -> /fr_BE. The cookie
        # records the URL's own lang, so a bare /<lang>/ does not redirect
        # claiming the wrong frontend_lang.
        elif path == f"/{url_lang_str}/" and allow_redirect:
            _logger.debug(
                "%r (lang: %r) homepage with trailing slash, redirect",
                path,
                request_url_code,
            )
            cls._redirect_lang(path[:-1], code=301)

        # See /9, valid lang in url. ``url_lang_str`` survives only when it
        # resolved to a real frontend lang (``nearest_url_lang`` in
        # :meth:`_match`), so stripping it is always safe -- including the
        # aliases cases /6 and /7 redirect when redirecting is allowed, which is
        # how ``POST /fr_FR/foo`` gets served instead of 404ing.
        elif url_lang_str == request_url_code or not allow_redirect:
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
            # Redirect a bare-id URL to its canonical slug: '/foo/1' ->
            # '/foo/egg-1', or '/fr/foo/1' -> '/fr/foo/oeuf-1'. The pretty URL
            # is nice for humans; the real reason is SEO.
            if request.httprequest.method in _REDIRECTABLE_METHODS:
                _, path = rule.build(args)
                if path is None:
                    # ``Rule.build`` answers None when a converter's ``to_url``
                    # rejects the value (werkzeug swallows its ValidationError).
                    # The SEO redirect is a nicety: skip it and serve the page
                    # rather than 500 on ``unquote_plus(None)``.
                    _logger.warning(
                        "Cannot rebuild a canonical URL for rule %r, "
                        "serving %r without the slug redirect",
                        rule.rule,
                        request.httprequest.path,
                    )
                    return
                generated_path = urllib.parse.unquote_plus(path)
                current_path = urllib.parse.unquote_plus(request.httprequest.path)
                if generated_path != current_path:
                    if request.lang != request.env["ir.http"]._get_default_lang():
                        path = cls._lang_url_prefix(path, request.lang.url_code)
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
        """Return the error code followed by the values matching the exception."""
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
            # A bare werkzeug HTTPException carries ``code = None``; guard so
            # this re-raises cleanly instead of raising TypeError.
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
        if not getattr(request, "lang", None):
            # ``_match`` flags ``is_frontend`` before ``_resolve_frontend_lang``
            # runs, so anything raising in between arrives with no
            # ``request.lang``, and ``_frontend_pre_dispatch`` would mask the
            # real exception with an AttributeError.
            request.lang = request.env["ir.http"]._get_default_lang()
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
            # The first render may have aborted the PG transaction (e.g. an
            # asset-bundle INSERT on a read-only cursor). Without this rollback
            # the fallback SELECT fails with "current transaction is aborted"
            # and the user sees a 500 instead of this simpler error page.
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
    def url_rewrite(self, path: str) -> tuple[str, typing.Any]:
        """Resolve ``path`` against the routing table.

        :return: ``(path, endpoint)`` -- the possibly-rewritten path (a redirect
                 rule reports its target) and the endpoint serving it, with
                 ``endpoint`` ``False`` when nothing matches.
        """
        # The query string stays out of the cache key: a redirect rule builds
        # its target from the rule alone.
        return self._url_rewrite(path, frozenset())

    def _url_rewrite(
        self, path: str, _visited: frozenset[str]
    ) -> tuple[str, typing.Any]:
        """Uncached body of :meth:`url_rewrite`.

        Redirect chains recurse here, not through the cached wrapper: inside a
        cycle the node reached second returns early on the ``_visited`` check,
        so memoizing that result would pin the cycle to whichever path was
        resolved first.
        """
        # Resolve the routing map from ``self.env``, not the ambient request:
        # the cache already lives on the registry, so a pure routing lookup
        # must not require a request to exist.
        router = http.root.get_db_router(self.env.registry.db_name, env=self.env).bind(
            ""
        )
        try:
            try:
                func, _args = router.match(path, method="POST")
            except werkzeug.exceptions.MethodNotAllowed:
                func, _args = router.match(path, method="GET")
        except werkzeug.routing.RequestRedirect as e:
            # ``e.new_url`` is absolute ("http://host/path?qs"); ``urlsplit``
            # keeps only the path whatever the scheme/host, where a hardcoded
            # prefix strip would not. Recurse for the target's own endpoint,
            # but report the first target as the rewritten path.
            new_path = urllib.parse.urlsplit(e.new_url).path
            if new_path == path or new_path in _visited:
                # A redirect cycle (e.g. two website.rewrite 308 rules mapping
                # /a -> /b and /b -> /a) must not recurse forever: report the
                # path unroutable rather than RecursionError every render.
                _logger.warning(
                    "Redirect loop while rewriting %r (targets %r again)",
                    path,
                    new_path,
                )
                return path, False
            _, func = self._url_rewrite(new_path, _visited | {path})
            return new_path or path, func
        except HTTPException:
            # Any routing exception other than a redirect means "no endpoint we
            # can name", including MethodNotAllowed for a rule that accepts
            # neither POST nor GET (``methods=['PUT']``); the callers in
            # ``website``/``website_sale`` do not guard this call.
            # ``RequestRedirect`` is an ``HTTPException`` too, but the clause
            # above runs first.
            return path, False
        return path, func
