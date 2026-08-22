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
    lang_code = context.get("lang", env.context.get("lang", "en_US"))
    env = env(context=dict(context, lang=lang_code))
    if HttpCase.http_port():
        base_url = HttpCase.base_url()
    else:
        base_url = f"http://{HOST}:{config['http_port']}"
    request = Mock(
        httprequest=Mock(
            host="localhost",
            path=path,
            method=method,
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
    request.make_response = partial(odoo.http.Request.make_response, request)
    request.make_json_response = partial(odoo.http.Request.make_json_response, request)
    request.redirect = partial(odoo.http.Request.redirect, request)
    request.redirect_query = partial(odoo.http.Request.redirect_query, request)
    if url_root is not None:
        request.httprequest.url = url_join(url_root, path)
    request.website_routing = website.id if website else False
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
