import collections.abc
import functools
from typing import TYPE_CHECKING, Any

from .constants import (
    _GEOIP_NULL,
    GEOIP_EMPTY_CITY,
    GEOIP_EMPTY_COUNTRY,
    geoip2,
    maxminddb,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _none_if_null(value: Any) -> Any:
    """Normalise the geoip2-absent null sentinel to ``None`` for *leaf* values.

    When geoip2 is not installed, ``GEOIP_EMPTY_COUNTRY`` / ``GEOIP_EMPTY_CITY``
    are :data:`~odoo.http.constants._GEOIP_NULL`, and attribute chains through it
    return the *same* sentinel rather than ``None``. That chaining is deliberate
    so intermediate access (``geoip.country``, ``geoip.location``) stays safe to
    dot through, but a scalar leaf (``country_code``, the ``city`` name, a
    ``time_zone`` ...) is documented — and behaves, when geoip2 *is* installed —
    as ``None`` when unresolved.

    A leaked ``_GeoIPNull`` breaks that contract in three concrete ways: it is
    ``is not None`` (so ``x is None`` guards miss it), it is not
    JSON-serialisable, and psycopg cannot adapt it as a SQL parameter — the last
    one turns ``website.visitor``'s ``country_code`` upsert into a hard error for
    every anonymous visitor on a deployment without geoip2. Coerce the sentinel
    to ``None`` at the leaf so the scalar/dict API keeps its contract regardless
    of whether geoip2 is installed. A genuine ``0`` / ``0.0`` (e.g. a latitude on
    the equator) is preserved — only the sentinel itself maps to ``None``.
    """
    return None if value is _GEOIP_NULL else value

# Sentinel exception tuple used in the ``except`` clauses below. When
# geoip2/maxminddb are not installed we cannot reference their exception
# classes — evaluating ``maxminddb.InvalidDatabaseError`` against ``None``
# would raise ``AttributeError`` at except-match time and replace the
# original error. Falling back to ``OSError`` alone in that case keeps
# the defensive fallback behaviour intact.
_GEOIP_DB_ERRORS: tuple[type[BaseException], ...] = (
    (OSError, maxminddb.InvalidDatabaseError) if maxminddb is not None else (OSError,)
)
_GEOIP_NOT_FOUND: type[BaseException] = (
    geoip2.errors.AddressNotFoundError if geoip2 is not None else LookupError
)
# A malformed or missing IP makes geoip2/maxminddb raise ``ValueError`` (via
# ``ipaddress.ip_address`` deep inside ``Reader.city``/``country``) or
# ``TypeError`` (when ``self.ip`` is ``None``) — NOT an ``AddressNotFoundError``.
# ``self.ip`` is ``request.httprequest.remote_addr``, which is attacker-influenced
# under ``proxy_mode`` (a forged ``X-Forwarded-For`` hop) and may be absent. The
# class contract (see :class:`GeoIP` docstring) is that a *bad address* yields an
# empty record, so catch these and degrade to "no GeoIP context" instead of
# letting an un-geolocalizable address 500 a website page load
# (``website.ir_http`` reads ``request.geoip.location.time_zone`` unguarded).
_GEOIP_BAD_ADDRESS: tuple[type[BaseException], ...] = (ValueError, TypeError)


class GeoIP(collections.abc.Mapping):
    """
    Ip Geolocalization utility, determine information such as the
    country or the timezone of the user based on their IP Address.

    The instances share the same API as `:class:`geoip2.models.City`
    <https://geoip2.readthedocs.io/en/latest/#geoip2.models.City>`_.

    When the IP couldn't be geolocalized (missing database, bad address)
    then an empty object is returned. This empty object can be used like
    a regular one with the exception that all values are set to None.

    :param str ip: The IP Address to geo-localize

    .. note:

        The geoip info for the current request are available at
        :attr:`~odoo.http.request.geoip`.

    .. code-block:

        >>> GeoIP("127.0.0.1").country.iso_code
        >>> odoo_ip = socket.gethostbyname("odoo.com")
        >>> GeoIP(odoo_ip).country.iso_code
        'FR'
    """

    def __init__(self, ip: str, app: Any = None) -> None:
        # ``app`` is the :class:`Application` whose cached GeoIP ``Reader``s
        # this instance reads. :class:`~odoo.http.Request` injects its own
        # ``app``; the lazy fallback keeps standalone constructors
        # (``res.device``, tests) working without the module singleton on
        # their call site.
        if app is None:
            from .application import root

            app = root
        self.app = app
        self.ip = ip

    @functools.cached_property
    def _city_record(self):
        root = self.app

        # ``root.geoip_city_db`` is ``None`` when geoip2 is absent or the
        # database could not be opened (that failure is cached on ``root``).
        city_db = root.geoip_city_db
        if city_db is None:
            return GEOIP_EMPTY_CITY
        try:
            return city_db.city(self.ip)
        except _GEOIP_DB_ERRORS:
            return GEOIP_EMPTY_CITY
        except _GEOIP_NOT_FOUND:
            return GEOIP_EMPTY_CITY
        except _GEOIP_BAD_ADDRESS:  # malformed / missing IP -> empty, per contract
            return GEOIP_EMPTY_CITY

    @functools.cached_property
    def _country_record(self):
        root = self.app

        if "_city_record" in vars(self):
            # the City class inherits from the Country class and the
            # city record is in cache already, save a geolocalization
            return self._city_record
        # ``None`` when geoip2 is absent or the Country database could not be
        # opened; fall back to the City database, which yields an empty record
        # on its own failure — preserving the historical OSError→city fallback.
        country_db = root.geoip_country_db
        if country_db is None:
            return self._city_record
        try:
            return country_db.country(self.ip)
        except _GEOIP_DB_ERRORS:
            return self._city_record
        except _GEOIP_NOT_FOUND:
            return GEOIP_EMPTY_COUNTRY
        except _GEOIP_BAD_ADDRESS:  # malformed / missing IP -> empty, per contract
            return GEOIP_EMPTY_COUNTRY

    @property
    def country_name(self) -> str | None:
        return _none_if_null(self.country.name or self.continent.name)

    @property
    def country_code(self) -> str | None:
        return _none_if_null(self.country.iso_code or self.continent.code)

    def __getattr__(self, attr: str) -> Any:
        # Be smart and determine whether the attribute exists on the
        # country object or on the city object.
        if hasattr(GEOIP_EMPTY_COUNTRY, attr):
            return getattr(self._country_record, attr)
        if hasattr(GEOIP_EMPTY_CITY, attr):
            return getattr(self._city_record, attr)
        raise AttributeError(f"{self} has no attribute {attr!r}")

    def __bool__(self) -> bool:
        return bool(self.country_name)

    # Old dict API, undocumented for now, will be deprecated some day
    def __getitem__(self, item: str) -> Any:
        match item:
            case "country_name":
                return self.country_name
            case "country_code":
                return self.country_code
            case "city":
                return _none_if_null(self.city.name)
            case "latitude":
                return _none_if_null(self.location.latitude)
            case "longitude":
                return _none_if_null(self.location.longitude)
            case "region":
                return _none_if_null(
                    self.subdivisions[0].iso_code if self.subdivisions else None
                )
            case "time_zone":
                return _none_if_null(self.location.time_zone)
            case _:
                raise KeyError(item)

    def __iter__(self) -> Iterator[str]:
        msg = "The dictionary GeoIP API is deprecated."
        raise NotImplementedError(msg)

    def __len__(self) -> int:
        msg = "The dictionary GeoIP API is deprecated."
        raise NotImplementedError(msg)
