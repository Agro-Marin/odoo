from types import SimpleNamespace

import pytest
from werkzeug.exceptions import HTTPException

from odoo.http.dispatcher import (
    HttpDispatcher,
    Json2Dispatcher,
    JsonRPCDispatcher,
    infer_dispatcher_for_unmatched,
)
from odoo.http.wrappers import FutureResponse


class _FakeSession:
    can_save = True


def _request(method="GET", headers=None, mimetype="text/html"):
    return SimpleNamespace(
        session=_FakeSession(),
        future_response=FutureResponse(),
        httprequest=SimpleNamespace(
            method=method,
            headers=headers or {},
            mimetype=mimetype,
            max_content_length=None,
        ),
    )


def _rule(**routing):
    routing.setdefault("type", "http")
    routing.setdefault("methods", None)
    routing.setdefault("routes", ["/x"])
    return SimpleNamespace(endpoint=SimpleNamespace(routing=routing))


def _pre_dispatch(request, rule):
    dispatcher = HttpDispatcher(request)
    try:
        dispatcher.pre_dispatch(rule, {})
    except HTTPException as exc:
        return exc.get_response()
    return None


def test_credentialed_cors_echoes_the_origin_a_resolver_allows():
    req = _request(headers={"Origin": "https://app.example"})
    _pre_dispatch(
        req,
        _rule(
            cors=lambda r: r.httprequest.headers.get("Origin"), cors_credentials=True
        ),
    )

    headers = req.future_response.headers
    assert headers["Access-Control-Allow-Origin"] == "https://app.example"
    assert headers["Access-Control-Allow-Credentials"] == "true"
    assert "Origin" in headers["Vary"]


def test_a_resolver_that_declines_grants_nothing():
    req = _request(headers={"Origin": "https://evil.example"})
    _pre_dispatch(req, _rule(cors=lambda r: None, cors_credentials=True))

    headers = req.future_response.headers
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Credentials" not in headers
    assert headers["Vary"] == "Origin"


def test_a_resolver_varies_on_origin_even_without_credentials():
    req = _request(headers={"Origin": "https://app.example"})
    _pre_dispatch(req, _rule(cors=lambda r: "https://app.example"))

    headers = req.future_response.headers
    assert headers["Access-Control-Allow-Origin"] == "https://app.example"
    assert headers["Vary"] == "Origin"


def test_plain_cors_still_emits_the_declared_value():
    req = _request(headers={"Origin": "https://app.example"})
    _pre_dispatch(req, _rule(cors="*"))

    headers = req.future_response.headers
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Credentials" not in headers
    assert "Vary" not in headers


def test_credentialed_cors_emits_nothing_without_an_origin():
    req = _request()
    _pre_dispatch(req, _rule(cors="https://app.example", cors_credentials=True))

    headers = req.future_response.headers
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Credentials" not in headers
    assert headers["Vary"] == "Origin"


def test_credentialed_cors_refuses_an_origin_it_does_not_allow():
    req = _request(headers={"Origin": "https://evil.example"})
    _pre_dispatch(req, _rule(cors="https://app.example", cors_credentials=True))

    headers = req.future_response.headers
    assert "Access-Control-Allow-Origin" not in headers
    assert "Access-Control-Allow-Credentials" not in headers


def test_credentialed_preflight_varies_on_both_reasons():
    req = _request(
        method="OPTIONS",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Headers": "X-Foo",
        },
    )
    response = _pre_dispatch(
        req, _rule(cors="https://app.example", cors_credentials=True)
    )

    assert response.status_code == 204
    vary = req.future_response.headers["Vary"]
    assert "Origin" in vary
    assert "Access-Control-Request-Headers" in vary


def test_options_does_not_run_the_handler_on_an_unrestricted_route():
    req = _request(method="OPTIONS")
    response = _pre_dispatch(req, _rule())

    assert response is not None, "pre_dispatch must short-circuit"
    assert response.status_code == 204
    allow = response.headers["Allow"]
    assert "OPTIONS" in allow
    assert "POST" in allow


def test_options_still_reaches_a_route_that_declares_it():
    req = _request(method="OPTIONS")
    assert _pre_dispatch(req, _rule(methods=("POST", "OPTIONS"))) is None


def test_options_on_a_cors_route_is_still_the_preflight():
    req = _request(method="OPTIONS", headers={"Origin": "https://app.example"})
    response = _pre_dispatch(req, _rule(cors="*"))

    assert response.status_code == 204
    assert "Allow" not in response.headers
    assert req.future_response.headers["Access-Control-Max-Age"]


@pytest.mark.parametrize(
    ("mimetype", "expected"),
    [
        ("application/json-rpc", JsonRPCDispatcher),
        ("application/json", Json2Dispatcher),
        ("text/html", HttpDispatcher),
        ("application/x-www-form-urlencoded", HttpDispatcher),
        ("", HttpDispatcher),
    ],
)
def test_unmatched_dispatcher_is_inferred_from_content_type(mimetype, expected):
    assert infer_dispatcher_for_unmatched(_request(mimetype=mimetype)) is expected


def test_json_dispatchers_both_claim_application_json():
    assert "application/json" in JsonRPCDispatcher.mimetypes
    assert "application/json" in Json2Dispatcher.mimetypes


def test_unmatched_json_error_keeps_the_status_code():
    from werkzeug.exceptions import NotFound

    captured = {}

    class _Req:
        def make_json_response(self, data, headers=None, cookies=None, status=200):
            captured["status"] = status
            return data

    dispatcher = Json2Dispatcher(_Req())
    dispatcher.handle_error(NotFound())
    assert captured["status"] == 404
