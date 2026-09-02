import pytest
import werkzeug.datastructures

from odoo.http.wrappers import Headers, Response


def _real(*pairs):
    return werkzeug.datastructures.Headers(list(pairs))


def test_headers_len_matches_the_wrapped_headers():
    assert len(Headers(_real())) == 0
    assert len(Headers(_real(("X-A", "1"), ("X-B", "2")))) == 2


def test_empty_headers_are_falsy_like_the_wrapped_headers():
    assert not Headers(_real())
    assert Headers(_real(("X-A", "1")))


def test_headers_iterate_as_pairs():
    h = Headers(_real(("X-A", "1"), ("X-B", "2")))
    assert list(h) == [("X-A", "1"), ("X-B", "2")]
    assert dict(h) == {"X-A": "1", "X-B": "2"}


def test_headers_equality_against_real_headers_both_directions():
    real = _real(("X-A", "1"))
    assert Headers(_real(("X-A", "1"))) == real
    assert real == Headers(_real(("X-A", "1")))
    assert Headers(_real(("X-B", "2"))) != real
    assert real != Headers(_real(("X-B", "2")))


def test_headers_equality_between_two_facades():
    assert Headers(_real(("X-A", "1"))) == Headers(_real(("X-A", "1")))
    assert Headers(_real(("X-A", "1"))) != Headers(_real(("X-A", "2")))
    assert Headers(_real()) != object()


def test_headers_are_unhashable_like_the_wrapped_headers():
    with pytest.raises(TypeError):
        hash(Headers(_real()))


def test_response_headers_survive_the_protocol_round_trip():
    response = Response("body", headers=[("X-A", "1")])
    headers = response.headers
    assert len(headers) >= 1
    assert ("X-A", "1") in list(headers)
    assert headers == headers


def test_cache_control_contains_and_len():
    cc = Response("x").cache_control
    assert "max-age" not in cc
    assert len(cc) == 0
    cc.max_age = 60
    assert "max-age" in cc
    assert len(cc) == 1


def test_cache_control_get_iter_and_equality():
    cc = Response("x").cache_control
    assert cc.get("max-age") is None
    cc.max_age = 60
    assert cc.get("max-age") == "60"
    assert list(cc) == ["max-age"]
    assert cc == {"max-age": "60"}
    assert Response("x").cache_control == Response("x").cache_control
