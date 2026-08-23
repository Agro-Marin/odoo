"""What a ``/<module>/static/<path>`` URL answers, per verb.

The static branch runs in ``Application.__call__`` ahead of the router, so no
route can narrow it and nothing downstream ever sees the request. Until this
was pinned it served the file body for **every** verb: ``POST``, ``PUT``,
``PATCH`` and ``DELETE`` all came back ``200 OK`` with the asset in the body,
which tells a client its write succeeded, and ``OPTIONS`` answered a CORS
preflight with 1150 bytes of favicon.
"""

import types

import pytest
from werkzeug.exceptions import MethodNotAllowed

from odoo.http import Response
from odoo.http.application import Application
from odoo.http.constants import DEFAULT_ALLOWED_METHODS, allow_header

SERVED = object()


def _request(method):
    served = []
    return types.SimpleNamespace(
        httprequest=types.SimpleNamespace(method=method),
        _serve_static=lambda path: served.append(path) or SERVED,
        served=served,
    )


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_read_verbs_reach_the_file(method):
    request = _request(method)
    assert Application()._serve_static_file(request, "/tmp/asset.js") is SERVED
    assert request.served == ["/tmp/asset.js"]


def test_options_answers_the_allow_list_without_the_body():
    request = _request("OPTIONS")
    response = Application()._serve_static_file(request, "/tmp/asset.js")
    assert isinstance(response, Response)
    assert response.status_code == 204
    assert response.headers["Allow"] == "GET, HEAD, OPTIONS"
    assert request.served == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_verbs_are_refused_and_never_open_the_file(method):
    request = _request(method)
    with pytest.raises(MethodNotAllowed) as caught:
        Application()._serve_static_file(request, "/tmp/asset.js")
    assert caught.value.valid_methods == ["GET", "HEAD", "OPTIONS"]
    assert request.served == []


def test_allow_header_always_advertises_options():
    assert allow_header(("GET", "HEAD")) == "GET, HEAD, OPTIONS"
    assert allow_header() == ", ".join([*DEFAULT_ALLOWED_METHODS, "OPTIONS"])


def test_allow_header_does_not_repeat_a_declared_options():
    assert allow_header(("GET", "OPTIONS")) == "GET, OPTIONS"


def test_allow_header_is_parseable_back_into_valid_methods():
    assert allow_header(("GET",)).split(", ") == ["GET", "OPTIONS"]
