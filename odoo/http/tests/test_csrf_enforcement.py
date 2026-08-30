import logging
import types
from typing import Any

import pytest
import werkzeug.datastructures
from werkzeug.exceptions import BadRequest

from odoo.http.constants import MISSING_CSRF_WARNING
from odoo.http.dispatcher import HttpDispatcher, Json2Dispatcher


def _endpoint(**routing):
    seen = {}

    def handler(**params):
        seen.update(params)
        return "handled"

    endpoint: Any = handler
    endpoint.routing = {"type": "http", **routing}
    endpoint.seen = seen
    return endpoint


def _request(method="POST", params=None, db="db", valid=True, mimetype="", body=b""):
    empty = werkzeug.datastructures.MultiDict()

    class _Registry:
        def __getitem__(self, name):
            return types.SimpleNamespace(
                _dispatch=lambda endpoint: endpoint(**this.params)
            )

    this: Any = types.SimpleNamespace(
        db=db,
        registry=_Registry() if db else None,
        params=dict(params or {}),
        httprequest=types.SimpleNamespace(
            method=method,
            path="/probe",
            args=empty,
            form=empty,
            files=empty,
            mimetype=mimetype,
            get_data=lambda cache=True: body,
        ),
        validate_csrf=lambda token: valid,
        redirect=lambda location, **kw: ("redirected", location),
        get_json_data=dict,
    )
    this.get_http_params = lambda: dict(params or {})
    this.make_json_response = lambda data, **kw: ("json", data)
    return this


SAFE = ["GET", "HEAD", "OPTIONS"]
UNSAFE = ["POST", "PUT", "PATCH", "DELETE"]


@pytest.mark.parametrize("method", SAFE)
def test_a_safe_method_never_needs_a_token(method):
    req = _request(method=method, valid=False)
    assert HttpDispatcher(req).dispatch(_endpoint(), {}) == "handled"


@pytest.mark.parametrize("method", UNSAFE)
def test_every_state_changing_method_needs_a_token(method):
    req = _request(method=method, valid=False)
    with pytest.raises(BadRequest, match="invalid CSRF token"):
        HttpDispatcher(req).dispatch(_endpoint(), {})


@pytest.mark.parametrize("method", UNSAFE)
def test_csrf_false_opts_a_route_out(method):
    req = _request(method=method, valid=False)
    assert HttpDispatcher(req).dispatch(_endpoint(csrf=False), {}) == "handled"


def test_a_valid_token_passes_and_never_reaches_the_handler():
    endpoint = _endpoint()
    req = _request(params={"csrf_token": "t", "real": "1"}, valid=True)
    assert HttpDispatcher(req).dispatch(endpoint, {}) == "handled"
    assert endpoint.seen == {"real": "1"}
    assert "csrf_token" not in req.params


def test_without_a_database_the_user_is_sent_to_the_selector():
    req = _request(db=None, valid=False)
    result = HttpDispatcher(req).dispatch(_endpoint(), {})
    assert result == ("redirected", "/web/database/selector")


def test_a_missing_token_and_a_wrong_one_are_logged_differently(caplog):
    with caplog.at_level(logging.WARNING, logger="odoo.http.dispatcher"):
        with pytest.raises(BadRequest):
            HttpDispatcher(_request(valid=False)).dispatch(_endpoint(), {})
    missing = caplog.records[-1].msg
    assert missing == MISSING_CSRF_WARNING, "the long guidance is for the absent case"

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="odoo.http.dispatcher"):
        with pytest.raises(BadRequest):
            HttpDispatcher(
                _request(params={"csrf_token": "wrong"}, valid=False)
            ).dispatch(_endpoint(), {})
    assert "CSRF validation failed" in caplog.records[-1].msg


@pytest.mark.parametrize("method", UNSAFE)
def test_json2_refuses_a_state_change_without_the_json_content_type(method):
    req = _request(method=method, mimetype="application/x-www-form-urlencoded")
    with pytest.raises(BadRequest, match="application/json"):
        Json2Dispatcher(req).dispatch(_endpoint(type="json2"), {})


@pytest.mark.parametrize("method", SAFE)
def test_json2_allows_a_safe_method_with_any_content_type(method):
    req = _request(method=method, mimetype="text/plain")
    assert Json2Dispatcher(req).dispatch(_endpoint(type="json2"), {}) == (
        "json",
        "handled",
    )


def test_json2_allows_a_state_change_that_declares_json():
    req = _request(mimetype="application/json")
    assert Json2Dispatcher(req).dispatch(_endpoint(type="json2"), {}) == (
        "json",
        "handled",
    )


def test_json2_csrf_false_opts_out():
    req = _request(mimetype="text/plain")
    assert Json2Dispatcher(req).dispatch(_endpoint(type="json2", csrf=False), {}) == (
        "json",
        "handled",
    )
