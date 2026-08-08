import contextlib
from functools import partial
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import parse_qsl, urlparse

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import NotFound
from werkzeug.test import EnvironBuilder
from werkzeug.user_agent import UserAgent

import odoo.http
from odoo.fields import Command
from odoo.libs.web import urljoin as url_join
from odoo.tests import HOST, HttpCase
from odoo.tools import DotDict, config, frozendict


def setup_frontend_langs(env, langs, default):
    """Make ``langs`` the frontend languages and ``default`` the default one,
    whatever is installed on top of http_routing.

    :param langs: a ``res.lang`` recordset, the frontend languages
    :param default: a ``res.lang`` record, the default frontend language
    """
    # http_routing derives both from ``res.lang`` + ``ir.default``, but
    # ``website`` overrides ``_get_frontend``/``_get_default_lang`` to read
    # ``website.language_ids``/``default_lang_id``: configure whichever source
    # is in play, or the fixture silently configures nothing.
    env["ir.default"].set("res.partner", "lang", default.code)
    if "website" in env:
        env["website"].search([]).write(
            {
                "language_ids": [Command.set(langs.ids)],
                "default_lang_id": default.id,
            }
        )
    env.flush_all()
    env.registry.clear_cache()


@contextlib.contextmanager
def MockRequest(
    env,
    *,
    path="/mockrequest",
    method="GET",
    user_agent="",
    routing=True,
    multilang=True,
    context=frozendict(),
    cookies=frozendict(),
    country_code=None,
    city_name=None,
    website=None,
    remote_addr=HOST,
    environ_base=None,
    url_root=None,
    mock_router=True,
    is_frontend=True,
):
    """Mock of the ``http.request``, for tests that need frontend request state.

    Code touching only ``request.env`` can use ``self.env`` instead.
    """
    lang_code = context.get("lang", env.context.get("lang", "en_US"))
    env = env(context=dict(context, lang=lang_code))
    if HttpCase.http_port():
        base_url = HttpCase.base_url()
    else:
        base_url = f"http://{HOST}:{config['http_port']}"
    request = Mock(
        # request
        httprequest=Mock(
            host="localhost",
            path=path,
            # A real request always has a method, and production code branches
            # on it (``_REDIRECTABLE_METHODS``). Left to ``Mock``'s attribute
            # autovivification it is a truthy object that equals nothing, so
            # every such branch silently took its "unsafe method" side.
            method=method,
            # ``ir.http.is_a_bot()`` reads ``user_agent.string`` and substring-
            # matches it, which on a bare ``Mock`` raises TypeError ("argument
            # of type 'Mock' is not iterable") -- so the ladder's bot branch
            # (case /3) could not be reached from a unit test at all.
            user_agent=UserAgent(user_agent),
            app=odoo.http.root,
            environ=dict(
                EnvironBuilder(
                    path=path,
                    method=method,
                    base_url=base_url,
                    headers={"User-Agent": user_agent} if user_agent else None,
                    environ_base=environ_base,
                ).get_environ(),
                REMOTE_ADDR=remote_addr,
            ),
            cookies=cookies,
            referrer="",
            remote_addr=remote_addr,
            url_root=url_root,
            # A real ``httprequest.args`` is a MultiDict, and the code under
            # test uses it as one: ``keep_query()`` calls ``.getlist()`` on it
            # and the lang ladder forwards it whole to ``redirect_query``. An
            # empty list only happened to survive because those paths were never
            # reached with a query string.
            args=MultiDict(parse_qsl(urlparse(path).query)),
        ),
        type="http",
        future_response=odoo.http.FutureResponse(),
        params={},
        session=DotDict(
            odoo.http.get_default_session(),
            context={"lang": ""},
            force_website_id=website and website.id,
        ),
        geoip=odoo.http.GeoIP("127.0.0.1", app=odoo.http.root),
        db=env.registry.db_name,
        env=env,
        registry=env.registry,
        cookies=cookies,
        lang=env["res.lang"]._get_data(code=lang_code),
        website=website,
        render=lambda *a, **kw: "<MockResponse>",
    )
    # Real response builders, not ``Mock``'s attribute autovivification: a
    # ``type="http"`` route answering JSON returns
    # ``request.make_json_response(...)``, which ``route_wrapper`` validates
    # through ``Response.load`` and rejects as an invalid return value. Both
    # mixin methods are self-contained, so binding them is safe; ``render``
    # above stays stubbed because it needs the serving stack.
    request.make_response = partial(odoo.http.Request.make_response, request)
    request.make_json_response = partial(odoo.http.Request.make_json_response, request)
    # ``redirect`` / ``redirect_query`` are what the whole lang ladder redirects
    # *through* (``_redirect_lang``), and they are the pieces that force the
    # Location local, keep repeated query parameters, and append the query
    # before the fragment. ``redirect`` used to be stubbed with the *model*
    # method ``ir.http._redirect``, which takes no ``local=`` and so cannot be
    # called the way production calls it; anything else was left to ``Mock``, so
    # an assertion about a redirect tested the mock. Both are self-contained.
    request.redirect = partial(odoo.http.Request.redirect, request)
    request.redirect_query = partial(odoo.http.Request.redirect_query, request)
    if url_root is not None:
        request.httprequest.url = url_join(url_root, path)
    # ``website_routing`` must ALWAYS be a real value, never left to ``Mock``'s
    # attribute autovivification: ``website._url_for`` reads it unguarded and
    # feeds it to ``_rewrite_len``, which drops it into a ``website.rewrite``
    # search domain and blows up in psycopg with "cannot adapt type 'Mock'".
    # ``False`` is the "no specific website" value that domain expects.
    request.website_routing = website.id if website else False
    # ``is_frontend``/``is_frontend_multilang`` are stamped on the request by
    # ``ir.http._match``, and production code branches on their *absence*
    # (``hasattr(request, "is_frontend")`` short-circuits the whole lang ladder;
    # ``ir.qweb`` warns when it is missing). A bare ``Mock`` autovivifies them,
    # so pass ``is_frontend=None`` to simulate a not-yet-routed request; the
    # default keeps the "already routed" behaviour.
    if is_frontend is None:
        del request.is_frontend
        del request.is_frontend_multilang
    else:
        request.is_frontend = is_frontend
        request.is_frontend_multilang = is_frontend and multilang
    if country_code or city_name:
        request.geoip._city_record = odoo.http.geoip2.models.City(
            ["en"],
            country=(country_code and {"iso_code": country_code}) or {},
            city=(city_name and {"names": {"en": city_name}}) or {},
        )

    # Mock match() to return a fake (endpoint, args) tuple whose endpoint
    # carries a fake 'routing' attribute (routing=True) or to raise NotFound
    # (routing=False), mirroring werkzeug's real MapAdapter.match() contract so
    # callers may index *or* unpack it. Pass ``mock_router=False`` to skip the
    # mock and match against the real routing map instead.
    router = MagicMock()
    match = router.return_value.bind.return_value.match
    if routing:
        endpoint = Mock(
            routing={
                "type": "http",
                "website": True,
                "multilang": multilang,
            }
        )
        match.return_value = (endpoint, {})
    else:
        match.side_effect = NotFound

    def update_context(**overrides):
        request.env = request.env(context=dict(request.env.context, **overrides))

    request.update_context = update_context

    with contextlib.ExitStack() as s:
        odoo.http._request_stack.push(request)
        s.callback(odoo.http._request_stack.pop)
        if mock_router:
            s.enter_context(patch("odoo.http.root.get_db_router", router))

        yield request
