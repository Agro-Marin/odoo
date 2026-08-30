import types

import pytest
from werkzeug.exceptions import MethodNotAllowed

from odoo.http import Response
from odoo.http.application import Application
from odoo.http.constants import DEFAULT_ALLOWED_METHODS, allow_header

SERVED = object()


def _request(method):
    served: list[str] = []

    def _serve_static(path):
        served.append(path)
        return SERVED

    return types.SimpleNamespace(
        httprequest=types.SimpleNamespace(method=method),
        _serve_static=_serve_static,
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
    assert response.headers["X-Content-Type-Options"] == "nosniff"


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


def test_allow_header_treats_empty_as_a_declaration_not_an_absence():
    assert allow_header(()) == "OPTIONS"
    assert allow_header([]) == "OPTIONS"
    assert allow_header(None) == ", ".join([*DEFAULT_ALLOWED_METHODS, "OPTIONS"])


@pytest.mark.parametrize(
    "resource",
    [
        "\x00x.js",
        "a" * 5000 + ".js",
        "src/scss/primary_variables.scss/nested.js",
        "\udcff.js",
        "../../../../etc/passwd",
        "..%2f..%2f..%2fetc/passwd",
        "....//....//etc/passwd",
        "./../../odoo-bin",
        "/..//..//odoo-bin",
        "\\..\\..\\odoo-bin",
    ],
)
def test_get_static_file_answers_none_and_never_raises(resource):
    from odoo.modules import module as module_manager

    module_manager.initialize_sys_path()
    app = Application()
    if app.static_path("web") is None:
        pytest.skip("addons path not initialised in this environment")

    assert app.get_static_file(f"/web/static/{resource}") is None
