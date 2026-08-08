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

#: The route serving the frontend's web translations. Named once: the
#: controller registers it and :meth:`IrHttp.get_frontend_session_info` hands it
#: to the browser, and the two silently disagreeing means the frontend loads no
#: translations at all -- with no error anywhere to say so.
FRONTEND_TRANSLATIONS_ROUTE = "/website/translations"

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
        if not record.id:
            # Id ``0`` is the one id our slug grammar accepts that can never name
            # a record, and it used to slip through every guard: ``check_access``
            # filters ``self._ids`` on truthiness (``_check_access``), so a
            # "/<model>/0" URL got neither the MissingError nor the AccessError
            # the ORM raises for any other absent id -- and then died in
            # :meth:`IrHttp._pre_dispatch`, where ``_slug`` refuses to *produce*
            # a 0-id slug: an unauthenticated 500 on every frontend
            # ``<model(...)>`` route in the product ("/shop/0", "/blog/0", ...),
            # trivially reachable by any crawler or scanner.
            #
            # ``ValidationError`` is werkzeug's "this rule does not match": the
            # URL falls through to the remaining rules and, failing those, to a
            # clean 404 -- the same answer "/shop/999999" already gave.
            raise werkzeug.routing.ValidationError
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
            # ``ensure_one`` first: ``BaseModel.id`` answers ``_ids[0]`` for a
            # multi-record set, so slugging one silently produced a URL for
            # whichever record happened to come first -- a link to the wrong
            # page, with nothing to notice. The ``website`` override reads
            # ``seo_name`` and does raise ("Expected singleton"), so the same
            # mistake was loud or silent depending on the installed addons.
            identifier, name = value.ensure_one().id, value.display_name
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
        fragment ride along untouched ("/blog/my-blog-1?p=2" -> "/blog/1?p=2"),
        as does a trailing slash ("/blog/my-blog-1/" -> "/blog/1/").
        """
        # Cut the query/fragment off first: ``_unslug`` accepts "?" and "#" as
        # segment terminators, so the last ``split("/")`` chunk unslugs fine --
        # but replacing it wholesale would take "?page=2" down with the slug.
        path, suffix = cls._url_split_suffix(value)
        # A trailing slash makes the last chunk empty, which unslugs to nothing:
        # "/blog/my-blog-1/" came back verbatim, so the two spellings of one
        # page compared unequal in ``website.menu``'s active-menu test, which is
        # exactly the difference ``_unslug_url`` exists to erase.
        slash = "/" if path.endswith("/") and path != "/" else ""
        if slash:
            path = path[:-1]
        # str.split() always yields at least one element, so parts[-1] is safe.
        parts = path.split("/")
        slug_id = cls._unslug(parts[-1])[1]
        if slug_id is None:
            return value
        parts[-1] = str(slug_id)
        return "/".join(parts) + slash + suffix

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
    # URL grammar
    # ------------------------------------------------------------

    @classmethod
    def _url_split_suffix(cls, url: str) -> tuple[str, str]:
        """Split ``url`` into its path and its ``[?query][#fragment]`` suffix.

        RFC 3986 orders the components as path[?query][#fragment]: the fragment
        starts at the FIRST "#", and a "?" appearing after it belongs to the
        fragment, not to the query. Every helper below that reasons about a
        *path* -- matching a route, splitting a language prefix -- has to cut
        both off first, and has to cut them off in that order.

        This is the single place that knows it. Partitioning on "?" alone (what
        :meth:`_url_lang` and :meth:`_is_multilang_url` each used to do) leaves
        "#frag" glued to the path, so "/fr#top" reads as the single segment
        "fr#top", which is not a language: the prefix stays on and gets a second
        one stacked in front of it ("/fr/fr#top", a dead link on every anchor
        link to a localized homepage).

        :return: ``(path, suffix)``; ``path + suffix == url``.
        """
        head, hash_, fragment = url.partition("#")
        path, qmark, query = head.partition("?")
        return path, qmark + query + hash_ + fragment

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

    @api.model
    def _frontend_url_codes(self) -> list[str]:
        """Return the ``url_code`` of every frontend language.

        The single definition of "what may appear as a language prefix in a
        path". :meth:`_lang_url_split`, :meth:`_url_lang` and
        :meth:`_is_multilang_url` all answer from here, so a stack that narrows
        the frontend languages (``website`` scopes them per website) narrows all
        three at once, and they cannot drift apart.
        """
        return [info.url_code for info in self.env["res.lang"]._get_frontend().values()]

    @classmethod
    def _lang_url_split(
        cls, path: str, url_codes: list[str] | None = None
    ) -> tuple[str | None, str]:
        """Split a root-relative ``path`` into its leading language ``url_code``
        and the rest: the inverse of :meth:`_lang_url_prefix`.

        "/fr/shop" -> ``("fr", "/shop")``, a bare "/fr" (or "/fr/") ->
        ``("fr", "/")``, and an unprefixed path -> ``(None, path)``. Only a
        language's ``url_code`` is recognized, never its full ``code``: the
        ladder redirects "/fr_FR/..." to "/fr/..." (case /7) rather than
        treating it as a prefix here.

        ``path`` must be a *path*: cut the query and the fragment off first with
        :meth:`_url_split_suffix`, or "/fr#top" reads as the segment "fr#top".

        :param url_codes: the codes to recognize, defaulting to
                          :meth:`_frontend_url_codes` on the ambient request.
                          Passing them is what lets a request-free caller
                          (:meth:`_is_multilang_url`, a sitemap builder, a cron)
                          ask the question at all, and it keeps one answer for
                          one URL where a caller has already resolved the list.
        """
        if url_codes is None:
            url_codes = request.env["ir.http"]._frontend_url_codes()
        segments = path.split("/")
        if len(segments) > 1 and segments[1] in url_codes:
            return segments[1], "/" + "/".join(segments[2:])
        return None, path

    @classmethod
    def _lang_url_unprefix(cls, path: str, url_codes: list[str] | None = None) -> str:
        """Strip a leading frontend-language prefix off a root-relative
        ``path``. See :meth:`_lang_url_split`.
        """
        return cls._lang_url_split(path, url_codes)[1]

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
        # Guard non-local URLs: an absolute, protocol-relative ("//cdn/x.png")
        # or non-http ("mailto:", "#anchor") URL would otherwise be
        # percent-quoted *as a path* and lang-prefixed ("https://odoo.com/shop"
        # -> "/frhttps%3A//odoo.com/shop"). A falsy ``url`` still means "derive
        # the path from the request", further down.
        #
        # This looks like :meth:`_url_lang`'s scheme/netloc guard and is NOT the
        # same question, so do not "de-duplicate" the two. That one asks "is
        # this *relative*", so that ``urljoin`` can root it against the current
        # page: with a language forced it deliberately accepts a bare fragment
        # or query and answers "/fr/current/page#anchor" -- which is what a
        # language switcher wants. This one asks "is this already a root-relative
        # path I can match against the routing table", and a bare "#anchor" is
        # not one.
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

        # Only the path routes: strip the query and the fragment before matching
        # ("/shop#top" would otherwise match no rule and come back
        # percent-quoted as "/fr/shop%23top", a dead link), and reattach them
        # verbatim at the end. '/shop/furn-0269-chaise-de-bureau-noire-17?' must
        # likewise lose its trailing '?' before matching, otherwise -> 404.
        url, suffix = cls._url_split_suffix(url)

        # Drop a lang prefix the caller already applied. This helper *sets* the
        # language of a URL, so localizing "/fr/shop" to fr must yield
        # "/fr/shop", not "/fr/fr/shop" -- which is what the match-then-prefix
        # sequence below produces on its own, since "/fr/shop" matches no rule.
        # :meth:`_url_lang` has always replaced the prefix rather than stacking
        # onto it; this aligns the two.
        url = cls._lang_url_unprefix(url)

        # One router for both halves: the map matched against MUST be the map
        # built from, or a path could be resolved on one routing table and
        # rebuilt on another. Matching went through ``ir.http.routing_map()``
        # while building went through ``http.root.get_db_router()``; the two
        # agree today only because the latter delegates to the former whenever
        # a database is known.
        router = http.root.get_db_router(request.db, env=request.env)
        try:
            # Match the routing map directly, never ``ir.http._match``: that is
            # the dispatch entry point and it mutates the live request (it
            # stamps ``is_frontend``/``lang``, and case /9 reroutes the request
            # being served). A URL-generation helper must observe the routing
            # table, never steer it.
            rule, args = router.bind_to_environ(request.httprequest.environ).match(
                path_info=url, return_rule=True
            )
            for key, val in list(args.items()):
                if isinstance(val, models.BaseModel):
                    if isinstance(val.env.uid, RequestUID):
                        args[key] = val = val.with_user(request.env.uid)
                    if val.env.context.get("lang") != lang.code:
                        args[key] = val = val.with_context(lang=lang.code)
                    if prefetch_langs:
                        args[key] = val = val.with_context(prefetch_langs=True)
            path = router.bind("").build(rule.endpoint, args)
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
            # canonical URLs carry neither a query string nor a fragment
            return tools.urls.urljoin(canonical_domain, path)

        return path + suffix

    @classmethod
    def _url_lang(cls, path_or_uri: str, lang_code: str | None = None) -> str:
        """Make a relative URL absolute and add or strip its lang prefix.

        An absolute or invalid URL comes back untouched. With a single installed
        language the prefix is left alone unless ``lang_code`` forces it.

        :param lang_code: the lang ``code``, or a placeholder such as
                          ``'[lang]'`` (used for url_return).
        """
        Lang = request.env["res.lang"]
        # ``or ""``: a falsy URL is a caller's slip, not a reason to take the
        # surrounding render down with an AttributeError. ``website``'s
        # ``_url_for`` already coerces before delegating here, so without this
        # the same call crashed or not depending on which addons were installed.
        location = (path_or_uri or "").strip()
        force_lang = lang_code is not None
        try:
            url = urllib.parse.urlparse(location)
        except ValueError:
            # e.g. Invalid IPv6 URL, `urllib.parse.urlparse('http://]')`
            url = False
        # relative URL with either a path or a force_lang
        if url and not url.netloc and not url.scheme and (url.path or force_lang):
            location = urllib.parse.urljoin(request.httprequest.path, location)
            lang_url_codes = request.env["ir.http"]._frontend_url_codes()
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
            # Resolved once: with ``website`` installed ``_get_default_lang``
            # reads the current website, so calling it per branch cost the hot
            # URL-building path an extra lookup per generated link.
            default_url_code = request.env["ir.http"]._get_default_lang().url_code
            if lang_url_code is None:
                lang_url_code = default_url_code
            if (len(lang_url_codes) > 1 or force_lang) and request.env[
                "ir.http"
            ]._is_multilang_url(location, lang_url_codes):
                # ``_url_split_suffix`` cuts the fragment as well as the query:
                # partitioning on "?" alone left "#top" glued to the path, so
                # "/fr#top" was not recognized as already carrying a language
                # and came back as "/fr/fr#top".
                loc, suffix = cls._url_split_suffix(location)
                # Normalize the trailing slash once, for every branch below.
                # Only the "insert a prefix" branch used to drop it, so the
                # three spellings of one link were rebuilt three different ways:
                # "/shop/" -> "/fr/shop" (no redirect) but "/en/shop/" ->
                # "/shop/" and forcing fr on it -> "/fr/shop/", each of which
                # costs the visitor a 308 to the slashless form. The endpoint
                # serves the same page either way, so emit the form that does
                # not bounce.
                if loc.endswith("/") and loc != "/":
                    loc = loc[:-1]
                # ``_lang_url_split`` / ``_lang_url_prefix`` are the two
                # primitives that know how a language sits in a path; splicing
                # ``loc.split("/")`` by hand here was a third implementation of
                # the same grammar, free to drift from the ladder's. Pass the
                # codes we already resolved rather than making it look them up
                # again -- this runs once per generated link.
                url_code, rest = cls._lang_url_split(loc, lang_url_codes)
                if url_code is not None:
                    # Replace the language only if we explicitly provide a language to url_for
                    if force_lang:
                        loc = cls._lang_url_prefix(rest, lang_url_code)
                    # Remove the default language unless it's explicitly provided
                    elif url_code == default_url_code:
                        loc = rest
                # Insert the context language or the provided language
                elif lang_url_code != default_url_code or force_lang:
                    loc = cls._lang_url_prefix(rest, lang_url_code)

                location = loc + suffix
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

    @api.model
    def _is_multilang_url(
        self, local_url: str, lang_url_codes: list[str] | None = None
    ) -> bool:
        """Whether the content served at ``local_url`` is translated.

        ``/static/`` and ``/web/`` paths never are. Any other path is, unless it
        resolves to an endpoint that is not ``website=True``, or whose
        ``multilang`` (defaulting to ``type == 'http'``) is false. A path
        matching no endpoint at all is translatable.

        Answers from ``self.env`` -- like :meth:`url_rewrite`, which it delegates
        the routing probe to -- so a sitemap builder, a cron or a test can ask
        the question without an ambient HTTP request.
        """
        if not lang_url_codes:
            lang_url_codes = self.env["ir.http"]._frontend_url_codes()
        # Strip the query and the fragment FIRST, then the language prefix.
        # Doing it the other way round -- which is what splicing
        # ``local_url.split("/")`` by hand here did -- made "/en#top" read as
        # the single segment "en#top", so the language was not recognized and
        # the routing probe ran against "/en" instead of "/", asking the routing
        # table about the wrong path. On a stack where "/" is a frontend route
        # both happen to answer True, so this is a latent inconsistency rather
        # than an observed wrong answer (measured: no output change across a
        # 3120-case differential run with ``website`` installed) -- but the
        # reasoning was wrong, and ``_lang_url_split`` is the one primitive that
        # knows this grammar. It used to have a fourth, divergent copy here.
        path, _suffix = self._url_split_suffix(local_url)
        path = self._lang_url_unprefix(path, lang_url_codes)

        # Consider /static/ and /web/ files as non-multilang
        if "/static/" in path or path.startswith("/web/"):
            return False

        # Try to match an endpoint in werkzeug's routing table
        try:
            _, func = self.env["ir.http"].url_rewrite(path)

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
        lang_code = self._get_default_lang_code()
        lang = Lang._get_data(code=lang_code) if lang_code else None
        if not lang:  # LangData.__bool__ is bool(self.id): a dummy is falsy
            lang = next(iter(Lang._get_active_by("code").values()))
        return lang

    @api.model
    def get_frontend_session_info(self) -> dict:
        session_info = super().get_frontend_session_info()

        # ``getattr``, not ``request.is_frontend``: a request that never went
        # through :meth:`_match` carries neither attribute (``ir.qweb`` warns
        # about exactly that case, e.g. an ``auth='none'`` controller building
        # its own registry), and this must not turn that into an AttributeError
        # that masks the real problem.
        if getattr(request, "is_frontend", False):
            session_info["bundle_params"]["lang"] = request.lang.code
        session_info.update(
            {
                "translationURL": FRONTEND_TRANSLATIONS_ROUTE,
            }
        )
        return session_info

    @api.model
    def get_translation_frontend_modules(self) -> list[str]:
        """Return the modules whose web translations the frontend may load.

        Read ``self.env``, not ``request.env``: this is the allow-list the
        public ``/website/translations`` route serves, and asserting on it --
        or precomputing it from a cron or a test -- must not require an
        ambient HTTP request.
        """
        Modules = self.env["ir.module.module"].sudo()
        # Copy: the ``+=`` below mutates in place, and an override is free to
        # answer with a module-level constant rather than a fresh list -- which
        # this would then grow, permanently, once per call.
        extra_modules_name = list(self._get_translation_frontend_modules_name())
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
            # Bind the two models once: ``_auth_method_public`` has just
            # swapped ``request.env``, so every ``request.env[...]`` below
            # rebuilt the same two registry entries -- five lookups for one
            # decision, on every frontend request.
            IrHttp = request.env["ir.http"]
            Lang = request.env["res.lang"]
            nearest_url_lang = IrHttp.get_nearest_lang(
                Lang._get_data(url_code=url_lang_str).code or url_lang_str
            )
            cookie_lang = IrHttp.get_nearest_lang(request.cookies.get("frontend_lang"))
            context_lang = IrHttp.get_nearest_lang(real_env.context.get("lang"))
            default_lang = IrHttp._get_default_lang()
            request.lang = Lang._get_data(
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
                try:
                    built, error = rule.build(args), None
                except (ValueError, TypeError, werkzeug.routing.ValidationError) as exc:
                    # ``rule.build`` runs every converter's ``to_url``, i.e.
                    # arbitrary code: ``_slug`` raises ValueError on an id it
                    # refuses to slug, ``<any(...)>`` raises ValueError on a
                    # value outside its list. Neither is a ``ValidationError``,
                    # so werkzeug does *not* swallow them into the None return
                    # this used to (try to) check for -- and a cosmetic redirect
                    # took the whole page down with a 500 instead.
                    #
                    # Deliberately NOT caught: MissingError and AccessError.
                    # ``_slug`` reads ``display_name``, so those mean the record
                    # named by the URL is gone or unreadable, and the 404 they
                    # produce is the right answer -- indeed the *only* one for a
                    # model without record rules, since ``check_access`` passes
                    # a nonexistent id straight through (``_check_access`` only
                    # runs ``ir.rule`` against it). Swallowing them served a 200
                    # for a record that does not exist.
                    built, error = None, exc
                if not built:
                    # ``Rule.build`` also answers a bare None -- not
                    # ``(_, None)``, which is why unpacking it straight into
                    # ``_, path`` raised TypeError before it could be checked.
                    _logger.warning(
                        "Cannot rebuild a canonical URL for rule %r (%s), "
                        "serving %r without the slug redirect",
                        rule.rule,
                        error or "a converter rejected the value",
                        request.httprequest.path,
                    )
                    return
                _, path = built
                # ``rule.build`` percent-quotes its output; ``httprequest.path``
                # is what werkzeug has *already* decoded. Decode the generated
                # side once so the two are compared like with like.
                #
                # Decoding the current path a second time turned a literal
                # "%20" (or "%2B", "%3D", ...) inside a converter value back
                # into a space, so the comparison could never match and the
                # "canonical" redirect pointed straight at the URL being served
                # -- an infinite 301 loop, on any frontend multilang route whose
                # segment carries a percent-escape-looking string: a coupon
                # code, a blog tag, a model-page record slug. 301s are cached by
                # browsers, so the URL stayed broken for that visitor well past
                # the fix.
                #
                # ``unquote``, not ``unquote_plus``: "+" is a literal plus in a
                # path (RFC 3986), and werkzeug's converters keep it unquoted
                # for exactly that reason. Plus-as-space is a query-string
                # convention and has no business here.
                generated_path = urllib.parse.unquote(path)
                current_path = request.httprequest.path
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
        """Return the HTTP status of ``exception``, and the values the error
        template renders with.

        The first element is a *status*, always, and overrides must keep it one:
        :meth:`_handle_error` decides from it whether :meth:`_serve_fallback`
        gets a chance, and ``Response(status=...)`` is built from it. To render a
        different page for the same status, override :meth:`_get_error_template`
        -- it receives these ``values``, ``exception`` included.
        """
        code = 500  # default code
        values = {
            "exception": exception,
            "traceback": "".join(traceback.format_exception(exception)),
        }

        if isinstance(exception, exceptions.UserError):
            code = exception.http_status
            values["error_message"] = exception.args[0]
        elif isinstance(exception, werkzeug.exceptions.HTTPException):
            # ``HTTPException`` itself carries ``code = None``, and
            # ``Response(status=None)`` answers *200 OK* with an error page in
            # the body. A code-less one does not reach this method today
            # (``Request._serve_db`` hands it to ``_serve_aborted`` instead), so
            # this is defence, not a live fix -- but ``values`` below are derived
            # from ``code``, and a page titled "None: " helps nobody either.
            code = exception.code or 500
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
    def _get_error_template(cls, code: int, values: dict[str, typing.Any]) -> str:
        """Return the xmlid of the template rendering the error page.

        The extension point for "same status, different page". It exists so that
        nobody has to smuggle a template through the *status*:
        :meth:`_get_exception_code_values` used to be the only hook, so
        ``website`` answered "page_404" there -- which then made
        :meth:`_handle_error`'s ``code in (404, 403)`` false and silently denied
        a website designer the :meth:`_serve_fallback` attempt a visitor got.

        ``values`` carries the ``exception`` itself, so an override can key off
        it exactly as it used to.
        """
        return "http_routing.%s" % code

    @classmethod
    def _get_error_html(
        cls, env, code: int, values: dict[str, typing.Any]
    ) -> tuple[int, typing.Any]:
        """Render the frontend error page for ``code``.

        :return: ``(code, html)`` -- ``code`` comes back unchanged; only the
                 template varies with it.
        """
        View = env["ir.ui.view"]
        try:
            return code, View._render_template(
                cls._get_error_template(code, values), values
            )
        except MissingError:
            # No dedicated template for this status. Degrade to a generic one
            # while *keeping the status*: re-raising sent the caller into
            # :meth:`_handle_error`'s last-resort branch, which answers "418 I'm
            # a teapot". A 502/503 reported as a 418 misleads clients, caches,
            # uptime monitors and crawlers alike -- and that branch exists for
            # "rendering itself blew up", not for "no template named 503".
            if not isinstance(code, int):
                raise
            return code, View._render_template(
                "http_routing.4xx" if 400 <= code < 500 else "http_routing.http_error",
                values,
            )

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
