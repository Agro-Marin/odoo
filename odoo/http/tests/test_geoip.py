"""DB-free unit tests for the geoip null-sentinel, now colocated in geoip.py.

Run via ``pytest odoo/http/tests``.
"""

from odoo.http.geoip import _GEOIP_NULL, _GeoIPNull


def test_null_sentinel_is_chainable_and_falsy():
    n = _GeoIPNull()
    # arbitrarily deep attribute chains keep returning the same sentinel
    assert n.country.iso_code.anything is n
    assert n.location.latitude is n
    assert bool(n) is False


def test_null_sentinel_equals_none_only():
    assert (_GEOIP_NULL == None) is True  # noqa: E711
    assert (_GEOIP_NULL != None) is False  # noqa: E711
    # __eq__ tested directly (avoids a yoda-condition rewrite): only None/self match
    assert _GEOIP_NULL.__eq__(object()) is False
    assert _GEOIP_NULL.__eq__(_GEOIP_NULL) is True


def test_null_sentinel_empty_container_protocol():
    assert len(_GEOIP_NULL) == 0
    assert list(_GEOIP_NULL) == []
    assert str(_GEOIP_NULL) == ""
    import pytest

    with pytest.raises(IndexError):
        _ = _GEOIP_NULL[0]


def test_null_sentinel_hashes_like_none():
    assert hash(_GEOIP_NULL) == hash(None)
