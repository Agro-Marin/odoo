"""A status-less ``HTTPException`` must never materialise as ``200 OK``.

``HTTPException.code`` is ``None`` on the base class and on any subclass that
forgets to set it; werkzeug then builds ``Response(body, None, headers)``, and
``None`` means *use the default status*, which is 200. An error page served
with a 2xx is indexed by crawlers and reported healthy by monitors.

The guard lives in this package's ``HTTPException.get_response`` override
because that is the single funnel: ``_serve_aborted``, werkzeug's own
``HTTPException.__call__``, ``Application._finalize_error_response`` and any
addon that calls ``exc.get_response()`` all pass through it. It used to sit in
``_serve_aborted`` alone, which left ``_finalize_error_response`` -- the path
taken by an exception raised in ``__call__`` before ``_serve_db`` is entered --
building the same 200.
"""

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
