import contextlib
from unittest.mock import MagicMock, Mock, patch

from werkzeug.exceptions import NotFound
from werkzeug.test import EnvironBuilder

import odoo.http
from odoo.fields import Command
from odoo.libs.web.urls import urljoin as url_join
from odoo.tests import HOST, HttpCase
from odoo.tools import DotDict, config, frozendict


def setup_frontend_langs(env, langs, default):
    """Make ``langs`` the frontend languages and ``default`` the default one,
    whatever is installed on top of http_routing.

    http_routing derives both from ``res.lang`` + ``ir.default``, but ``website``
    overrides ``_get_frontend`` and ``_get_default_lang`` to read
    ``website.language_ids`` / ``website.default_lang_id`` instead. A fixture
    that only writes ``ir.default`` therefore silently configures nothing once
    ``website`` is installed, and every assertion about lang prefixes fails --
    which is exactly why this suite passed under ``-i http_routing`` but failed
    wholesale on a website database. Configure whichever source is in play.

    :param langs: a ``res.lang`` recordset, the frontend languages
    :param default: a ``res.lang`` record, the default frontend language
    """
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
    """Mock of the ``http.request``.

    NOTE: If you only use ``request.env`` in your code, you can replace it by
    ``self.env`` and don't need to use this class.
    It is in this module, because website adds properties which are not defined
    in base module.
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
            app=odoo.http.root,
            environ=dict(
                EnvironBuilder(
                    path=path,
                    base_url=base_url,
                    environ_base=environ_base,
                ).get_environ(),
                REMOTE_ADDR=remote_addr,
            ),
            cookies=cookies,
            referrer="",
            remote_addr=remote_addr,
            url_root=url_root,
            args=[],
        ),
        type="http",
        future_response=odoo.http.FutureResponse(),
        params={},
        redirect=env["ir.http"]._redirect,
        session=DotDict(
            odoo.http.get_default_session(),
            context={"lang": ""},
            force_website_id=website and website.id,
        ),
        geoip=odoo.http.GeoIP("127.0.0.1"),
        db=env.registry.db_name,
        env=env,
        registry=env.registry,
        cookies=cookies,
        lang=env["res.lang"]._get_data(code=lang_code),
        website=website,
        render=lambda *a, **kw: "<MockResponse>",
    )
    if url_root is not None:
        request.httprequest.url = url_join(url_root, path)
    # ``website_routing`` must ALWAYS be a real value, never left to ``Mock``'s
    # attribute autovivification. ``website._generate_routing_rules`` reads it
    # unguarded and drops it straight into a ``website.rewrite`` search domain,
    # so an auto-created ``Mock`` reaches psycopg and every helper that builds a
    # routing map blows up with "cannot adapt type 'Mock'" -- but only once
    # ``website`` is installed, which is why running this suite on a website
    # database used to fail wholesale while ``-i http_routing`` passed.
    # ``False`` is the "no specific website" value the rewrite domain expects.
    request.website_routing = website.id if website else False
    # ``is_frontend``/``is_frontend_multilang`` are stamped on the request by
    # ``ir.http._match``. Production code branches on their *absence*
    # (``if hasattr(request, "is_frontend")`` short-circuits the whole lang
    # ladder; ``ir.qweb`` warns when it is missing) -- but a bare ``Mock``
    # autovivifies every attribute, so ``hasattr`` was unconditionally True and
    # those branches were unreachable from any test. Pass ``is_frontend=None``
    # to simulate a request that has not been routed yet and actually exercise
    # them; the default keeps the historical "already routed" behaviour.
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

    # The following code mocks match() to return a fake (endpoint, args)
    # tuple whose endpoint carries a fake 'routing' attribute (routing=True)
    # or to raise a NotFound exception (routing=False), mirroring werkzeug's
    # real MapAdapter.match() contract so callers may index *or* unpack it.
    #
    #   router = odoo.http.root.get_db_router()
    #   func, args = router.bind(...).match(path)
    #   # arg routing is True => func.routing == {...}
    #   # arg routing is False => NotFound exception
    #
    # Pass ``mock_router=False`` to skip this mock entirely and match against
    # the real routing map (e.g. to exercise url_rewrite/_url_localized against
    # actual endpoints).
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
