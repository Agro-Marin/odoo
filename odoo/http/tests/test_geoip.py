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


def test_model_attr_sets_match_real_geoip2():
    """The hardcoded model-attribute sets used in geoip2-absent mode must not
    drift from the real geoip2 model surface (skipped when geoip2 is absent —
    then there is nothing to compare against)."""
    import pytest

    from odoo.http import geoip as geoip_mod

    if geoip_mod.geoip2 is None:
        pytest.skip("geoip2 not installed")

    def real(o):
        return {
            a for a in dir(o) if not a.startswith("_") and not callable(getattr(o, a))
        }

    country = real(geoip_mod.geoip2.models.Country({}))
    city = real(geoip_mod.geoip2.models.City({}))
    assert frozenset(country) == geoip_mod._GEOIP_COUNTRY_MODEL_ATTRS
    assert frozenset(city - country) == geoip_mod._GEOIP_CITY_ONLY_MODEL_ATTRS


def test_getattr_typo_raises_even_without_geoip2():
    """Regression: with geoip2 absent, ``hasattr`` probes against the null
    sentinel answered True for ANY name, so a typo'd attribute chained
    silently here while raising AttributeError on a geoip2-equipped host."""
    import types

    import pytest

    from odoo.http import geoip as geoip_mod
    from odoo.http.geoip import _GEOIP_NULL, GeoIP

    app = types.SimpleNamespace(geoip_city_db=None, geoip_country_db=None)
    saved = (
        geoip_mod.geoip2,
        geoip_mod.GEOIP_EMPTY_COUNTRY,
        geoip_mod.GEOIP_EMPTY_CITY,
    )
    geoip_mod.geoip2 = None
    geoip_mod.GEOIP_EMPTY_COUNTRY = _GEOIP_NULL
    geoip_mod.GEOIP_EMPTY_CITY = _GEOIP_NULL
    try:
        geo = GeoIP("127.0.0.1", app=app)
        # real model attributes still chain to the (null) records
        assert geo.location is _GEOIP_NULL
        assert geo.country is _GEOIP_NULL
        # a typo raises, exactly like on a geoip2-equipped host
        with pytest.raises(AttributeError):
            _ = geo.locatoin
    finally:
        geoip_mod.geoip2, geoip_mod.GEOIP_EMPTY_COUNTRY, geoip_mod.GEOIP_EMPTY_CITY = (
            saved
        )
