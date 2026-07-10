import hashlib
import logging
import os
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any

import werkzeug.exceptions
import werkzeug.routing
import werkzeug.utils
from werkzeug.datastructures import WWWAuthenticate
from werkzeug.exceptions import Unauthorized
from werkzeug.routing.converters import NumberConverter

import odoo
from odoo import api, http, models, tools
from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessDenied
from odoo.http import SAFE_HTTP_METHODS, Response, request, rule_routing_kwargs
from odoo.libs.constants import EXTENSION_TO_WEB_MIMETYPES
from odoo.libs.json import OPT_SORT_KEYS
from odoo.libs.json import dumps_bytes as json_dumps_bytes
from odoo.modules.registry import Registry
from odoo.service import security
from odoo.tools.json import json_default
from odoo.tools.misc import get_lang, str2bool
from odoo.tools.translate import code_translations

_logger = logging.getLogger(__name__)

# Pre-compiled regexes for URL slugification
_SLUG_SPLIT_RE = re.compile(r"[-_ ]")
_SLUG_NONWORD_RE = re.compile(r"[^\w]+")


class RequestUID:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class ModelConverter(werkzeug.routing.BaseConverter):
    regex = r"[0-9]+"

    def __init__(self, url_map: Any, model: str | bool = False) -> None:
        super().__init__(url_map)
        self.model = model

        IrHttp = Registry(threading.current_thread().dbname)["ir.http"]
        self.slug = IrHttp._slug
        self.unslug = IrHttp._unslug

    def to_python(self, value: str) -> models.BaseModel:
        _uid = RequestUID(value=value, converter=self)
        env = api.Environment(request.env.cr, _uid, request.env.context)
        return env[self.model].browse(self.unslug(value)[1])

    def to_url(self, value: models.BaseModel) -> str:
        return self.slug(value)


class ModelsConverter(werkzeug.routing.BaseConverter):
    regex = r"[0-9,]+"

    def __init__(self, url_map: Any, model: str | bool = False) -> None:
        super().__init__(url_map)
        self.model = model

    def to_python(self, value: str) -> models.BaseModel:
        _uid = RequestUID(value=value, converter=self)
        env = api.Environment(request.env.cr, _uid, request.env.context)
        return env[self.model].browse([int(v) for v in value.split(",") if v])

    def to_url(self, value: models.BaseModel) -> str:
        return ",".join(str(i) for i in value.ids)


class SignedIntConverter(NumberConverter):
    regex = r"-?\d+"
    num_convert = int


class LazyCompiledBuilder:
    def __init__(
        self,
        rule: werkzeug.routing.Rule,
        _compile_builder: Any,
        append_unknown: bool,
    ) -> None:
        self.rule = rule
        self._callable = None
        self._compile_builder = _compile_builder
        self._append_unknown = append_unknown

    def __get__(self, *args: Any) -> LazyCompiledBuilder:
        # Rule.compile binds the result via _compile_builder(...).__get__(self, None),
        # so the builder must be a descriptor; returning self here keeps this lazy
        # wrapper alive through that binding.
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._callable is None:
            self._callable = self._compile_builder(self._append_unknown).__get__(
                self.rule, None
            )
            del self.rule
            del self._compile_builder
            del self._append_unknown
        return self._callable(*args, **kwargs)


class FasterRule(werkzeug.routing.Rule):
    """Make ``_compile_builder`` lazy: it dominates routing-map generation but rules are rarely built."""

    def _compile_builder(self, append_unknown: bool = True) -> LazyCompiledBuilder:
        return LazyCompiledBuilder(self, super()._compile_builder, append_unknown)


class IrHttp(models.AbstractModel):
    _name = "ir.http"
    _description = "HTTP Routing"

    @classmethod
    def _slugify_one(cls, value: str, max_length: int | None = None) -> str:
        """Transform a string into a slug usable in a URL path.

        Example: ^h☺e$#!l(%l}o 你好& becomes hello-你好
        """
        uni = unicodedata.normalize("NFKD", value)
        slugified_segments = []
        for slug in _SLUG_SPLIT_RE.split(uni):
            slug = _SLUG_NONWORD_RE.sub("", slug)
            if slug:
                slugified_segments.append(slug.lower())
        slugified_str = unicodedata.normalize("NFC", "-".join(slugified_segments))
        return slugified_str[:max_length]

    @classmethod
    def _slugify(
        cls, value: str, max_length: int | None = None, path: bool = False
    ) -> str:
        if not path:
            return cls._slugify_one(value, max_length=max_length)
        else:
            res = []
            for u in value.split("/"):
                s = cls._slugify_one(u, max_length=max_length)
                if s:
                    res.append(s)
            # check if supported extension
            p = Path(value)
            ext = p.suffix
            if ext in EXTENSION_TO_WEB_MIMETYPES and res:
                res[-1] = cls._slugify_one(p.stem) + ext
            return "/".join(res)

    @classmethod
    def _slug(cls, value: models.BaseModel | tuple[int, str]) -> str:
        if isinstance(value, tuple):
            return str(value[0])
        return str(value.id)

    @classmethod
    def _unslug(cls, value: str) -> tuple[None, int] | tuple[None, None]:
        try:
            return None, int(value)
        except ValueError:
            return None, None

    # ------------------------------------------------------
    # Routing map
    # ------------------------------------------------------

    @classmethod
    def _get_converters(cls) -> dict[str, type]:
        return {
            "model": ModelConverter,
            "models": ModelsConverter,
            "int": SignedIntConverter,
        }

    @classmethod
    def _match(cls, path_info: str) -> tuple[werkzeug.routing.Rule, dict[str, Any]]:
        rule, args = (
            request.env["ir.http"]
            .routing_map()
            .bind_to_environ(request.httprequest.environ)
            .match(path_info=path_info, return_rule=True)
        )
        return rule, args

    @classmethod
    def _get_public_users(cls) -> list[int]:
        return [
            request.env["ir.model.data"]._xmlid_to_res_model_res_id("base.public_user")[
                1
            ]
        ]

    @classmethod
    def _auth_method_bearer(cls) -> None:
        headers = request.httprequest.headers

        def get_http_authorization_bearer_token() -> str | None:
            # werkzeug<2.3 doesn't expose `authorization.token`; read the header directly.
            header = headers.get("Authorization")
            if header and (m := re.match(r"^bearer\s+(.+)$", header, re.IGNORECASE)):
                # strip trailing whitespace so it does not leak into the token
                return m.group(1).strip()
            return None

        def check_sec_headers() -> bool:
            """Check browser-set Sec-Fetch-* headers as CSRF protection.
            https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Sec-Fetch-User
            """
            return (
                headers.get("Sec-Fetch-Dest") == "document"
                and headers.get("Sec-Fetch-Mode") == "navigate"
                and headers.get("Sec-Fetch-Site") in ("none", "same-origin")
                and headers.get("Sec-Fetch-User") == "?1"
            )

        if token := get_http_authorization_bearer_token():
            # 'rpc' scope does not really exist, we require a global key (scope NULL)
            uid = request.env["res.users.apikeys"]._check_credentials(
                scope="rpc", key=token
            )
            if not uid:
                e = "Invalid apikey"
                raise Unauthorized(e, www_authenticate=WWWAuthenticate("bearer"))
            if request.env.uid and request.env.uid != uid:
                e = "Session user does not match the used apikey."
                raise AccessDenied(e)
            request.update_env(user=uid)
            request.session.can_save = False  # stateless
        elif not request.env.uid:
            e = "User not authenticated, use an API Key with a Bearer Authorization header."
            raise Unauthorized(e, www_authenticate=WWWAuthenticate("bearer"))
        elif not check_sec_headers():
            e = 'Missing "Authorization" or Sec-headers for interactive usage.'
            raise werkzeug.exceptions.Unauthorized(
                e, www_authenticate=WWWAuthenticate("bearer")
            )
        cls._auth_method_user()

    @classmethod
    def _auth_method_user(cls) -> None:
        if request.env.uid in [None] + cls._get_public_users():
            msg = "Session expired"
            raise http.SessionExpiredException(msg)

    @classmethod
    def _auth_method_none(cls) -> None:
        request.env = api.Environment(request.env.cr, None, request.env.context)
        request.env.transaction.default_env = request.env

    @classmethod
    def _auth_method_public(cls) -> None:
        if request.env.uid is None:
            public_user = request.env.ref("base.public_user")
            request.update_env(user=public_user.id)

    @classmethod
    def _authenticate(cls, endpoint: Any) -> None:
        auth = (
            "none"
            if http.is_cors_preflight(request, endpoint)
            else endpoint.routing["auth"]
        )
        cls._authenticate_explicit(auth)

    @classmethod
    def _authenticate_explicit(cls, auth: str) -> None:
        try:
            if request.session.uid is not None:
                if not security.check_session(request.session, request.env, request):
                    request.session.logout(keep_db=True)
                    request.env = api.Environment(
                        request.env.cr, None, request.session.context
                    )
            # `auth` comes from trusted route metadata, never request input;
            # an unknown value means a misconfigured @http.route. Fail closed
            # with a clear message instead of a confusing AttributeError log.
            auth_method = getattr(cls, f"_auth_method_{auth}", None)
            if auth_method is None:
                msg = f"Unknown authentication method: {auth!r}"
                raise AccessDenied(msg)
            auth_method()
        except (
            AccessDenied,
            http.SessionExpiredException,
            werkzeug.exceptions.HTTPException,
        ):
            raise
        except Exception as exc:
            _logger.info("Exception during request Authentication.", exc_info=True)
            raise AccessDenied from exc

    @classmethod
    def _geoip_resolve(cls) -> Any:
        return request._geoip_resolve()

    @classmethod
    def _sanitize_cookies(cls, cookies: Any) -> None:
        pass

    @classmethod
    def _pre_dispatch(cls, rule: werkzeug.routing.Rule, args: dict[str, Any]) -> None:
        ICP = request.env["ir.config_parameter"].with_user(SUPERUSER_ID)

        # Override the default 128MiB upload limit with the ICP value, before http's
        # generic pre_dispatch so a per-route @route(..., max_content_length=x) still wins.
        key = "web.max_file_upload_size"
        if (value := ICP.get_param(key, None)) is not None:
            try:
                request.httprequest.max_content_length = int(value)
            except ValueError:  # better not crash on ALL requests
                _logger.error(
                    "invalid %s: %r, using %s instead",
                    key,
                    value,
                    request.httprequest.max_content_length,
                )

        request.dispatcher.pre_dispatch(rule, args)

        # Ensure the context lang is valid, else fall back to company lang,
        # English, or the first installed lang.
        env = (
            request.env
            if request.env.uid
            else request.env["base"].with_user(SUPERUSER_ID).env
        )
        request.update_context(lang=get_lang(env).code)

        # Rebind record args to the current request.env before checking access.
        for key, val in list(args.items()):
            if not isinstance(val, models.BaseModel):
                continue

            args[key] = val.with_env(request.env)

        for key, val in list(args.items()):
            if not isinstance(val, models.BaseModel):
                continue

            try:
                # explicitly crash now, instead of crashing later
                args[key].check_access("read")
            except (
                odoo.exceptions.AccessError,
                odoo.exceptions.MissingError,
            ) as e:
                # custom behavior in case a record is not accessible / has been removed
                if handle_error := rule.endpoint.routing.get(
                    "handle_params_access_error"
                ):
                    if response := handle_error(e, **args):
                        werkzeug.exceptions.abort(response)
                if request.env.user.is_public or isinstance(
                    e, odoo.exceptions.MissingError
                ):
                    raise werkzeug.exceptions.NotFound from e
                raise

    @classmethod
    def _dispatch(cls, endpoint: Any) -> Any:
        # Verify the captcha in case it was set on @http.route
        # https://httpwg.org/specs/rfc9110.html#safe.methods
        if (
            captcha := endpoint.routing.get("captcha")
        ) and request.httprequest.method not in SAFE_HTTP_METHODS:
            request.env["ir.http"]._verify_request_recaptcha_token(captcha)
        result = endpoint(**request.params)
        if isinstance(result, Response) and result.is_qweb:
            result.flatten()
        return result

    @classmethod
    def _post_dispatch(cls, response: Response) -> None:
        request.dispatcher.post_dispatch(response)

    @classmethod
    def _post_logout(cls) -> None:
        pass

    @classmethod
    def _handle_error(cls, exception: Exception) -> Any:
        return request.dispatcher.handle_error(exception)

    @classmethod
    def _serve_fallback(cls) -> Response | None:
        model = request.env["ir.attachment"]
        # Only public attachments may be served by the URL fallback: the search runs
        # under sudo(), so without this filter any attachment whose url collides with
        # an unmatched path would leak to anonymous callers. See IHTTP-L3.
        attach = model.sudo()._get_serve_attachment(
            request.httprequest.path, extra_domain=[("public", "=", True)]
        )
        if attach and (attach.store_fname or attach.db_datas):
            return attach._to_http_stream().get_response()
        return None

    @classmethod
    def _redirect(cls, location: str, code: int = 303) -> Response:
        return werkzeug.utils.redirect(location, code=code, Response=Response)

    def _generate_routing_rules(
        self, modules: list[str], converters: dict[str, type]
    ) -> Any:
        return http._generate_routing_rules(modules, False, converters)

    @tools.ormcache("key", cache="routing")
    def routing_map(self, key: str | None = None) -> werkzeug.routing.Map:
        _logger.info("Generating routing map for key %s", key)
        installed = self.pool._init_modules.union(
            odoo.tools.config["server_wide_modules"]
        )
        mods = sorted(installed)
        # @tools.ormcache(cache="routing") caches and shares this map; it is rebuilt only
        # on a cache clear (every registry _setup_models__, i.e. every module install/upgrade/uninstall).
        routing_map = werkzeug.routing.Map(
            strict_slashes=False, converters=self._get_converters()
        )
        for url, endpoint in self._generate_routing_rules(
            mods, converters=self._get_converters()
        ):
            rule = FasterRule(url, endpoint=endpoint, **rule_routing_kwargs(endpoint))
            rule.merge_slashes = False
            routing_map.add(rule)
        return routing_map

    @api.autovacuum
    def _gc_sessions(self) -> None:
        # str2bool so documented off-values ("0"/"false"/"no"/...) don't count as
        # "set" and skip the GC (same pattern as ir_cron's ODOO_NOTIFY_CRON_CHANGES).
        if str2bool(os.getenv("ODOO_SKIP_GC_SESSIONS", ""), default=False):
            return
        http.root.session_store.vacuum(
            max_lifetime=http.get_session_max_inactivity(self.env)
        )

    @api.model
    def _get_translations_for_webclient(
        self, modules: list[str], lang: str | None
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if not lang:
            lang = self.env.context.get("lang")
        lang_data = self.env["res.lang"]._get_data(code=lang)
        lang_params = (
            {
                "name": lang_data.name,
                "code": lang_data.code,
                "direction": lang_data.direction,
                "date_format": lang_data.date_format,
                "time_format": lang_data.time_format,
                "grouping": lang_data.grouping,
                "decimal_point": lang_data.decimal_point,
                "thousands_sep": lang_data.thousands_sep,
                "week_start": int(lang_data.week_start),
            }
            if lang_data
            else None
        )

        # Regional languages (ll_CC) must inherit/override their parent lang (ll), but this is
        # done server-side when the language is loaded, so we only need to load the user's lang.
        translations_per_module = {}
        for module in modules:
            translations_per_module[module] = code_translations.get_web_translations(
                module, lang
            )

        return translations_per_module, lang_params

    @api.model
    @tools.ormcache("frozenset(modules)", "lang")
    def _get_web_translations_hash(self, modules: list[str], lang: str) -> str:
        translations, lang_params = self._get_translations_for_webclient(modules, lang)
        translation_cache = {
            "lang_parameters": lang_params,
            "modules": translations,
            "lang": lang,
            "multi_lang": len(self.env["res.lang"].sudo().get_installed()) > 1,
        }
        if self.env.context.get("cache_translation_data"):
            # put in the transactional cache
            self.env.cr.cache["translation_data"] = translation_cache
        return hashlib.sha1(
            json_dumps_bytes(
                translation_cache, default=json_default, option=OPT_SORT_KEYS
            )
        ).hexdigest()

    @classmethod
    def _is_allowed_cookie(cls, cookie_type: str) -> bool:
        return cookie_type == "required" or bool(request.env.user)

    @api.model
    def _verify_request_recaptcha_token(self, action: str) -> None:
        return
