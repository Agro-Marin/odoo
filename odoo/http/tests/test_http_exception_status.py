import werkzeug.exceptions
from werkzeug.exceptions import HTTPException

from odoo.http import Response


class _CodelessSubclass(HTTPException):
    pass


def test_a_bare_http_exception_becomes_a_500():
    response = HTTPException("no status here").get_response()
    assert response.status_code == 500
    assert b"no status here" in response.get_data()


def test_a_subclass_that_forgot_its_code_becomes_a_500():
    assert _CodelessSubclass().get_response().status_code == 500


def test_a_real_status_is_left_alone():
    response = werkzeug.exceptions.NotFound("nope").get_response()
    assert response.status_code == 404
    assert b"nope" in response.get_data()


def test_abort_with_a_response_is_delivered_verbatim():
    attached = Response(b"body", status=204)
    exc = werkzeug.exceptions.HTTPException(response=attached._wrapped__)
    assert exc.code is None

    response = exc.get_response()
    assert response.status_code == 204


def test_the_result_is_always_the_package_facade():
    assert isinstance(HTTPException().get_response(), Response)
    assert isinstance(werkzeug.exceptions.Gone().get_response(), Response)
