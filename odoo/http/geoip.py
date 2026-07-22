import collections.abc
import functools
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


# GeoIP / MaxMind — only available if geoip2 is installed (maxminddb is a
# transitive dependency, imported together so both are present or both ``None``).
# Code referencing ``maxminddb.InvalidDatabaseError`` /
# ``geoip2.errors.AddressNotFoundError`` in an ``except`` must guard with
# ``if geoip2 is not None`` — else the clause evaluates against ``None`` and
# raises AttributeError. These live here (the geoip domain module) rather than in
# ``constants``, which stays a leaf of plain literals with no third-party imports.


class _GeoIPNull:
    """Chainable null sentinel returned by :class:`GeoIP` when geoip2 isn't installed.

    Mimics an empty geoip2 record so chained access (``g.country.iso_code``,
    ``g.location.latitude``) returns this same instance instead of raising,
    while ``bool(g)`` and ``g == None`` are False/True respectively.
    """

    __slots__ = ()

    def __getattr__(self, _name):
        return self

    def __bool__(self):
        return False

    def __eq__(self, other):
        return other is self or other is None

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(None)

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __getitem__(self, _key):
        # Subdivisions[0] etc. are always gated by truthiness in callers.
        raise IndexError

    def __str__(self):
        return ""

    def __repr__(self):
        return "<GeoIPNull>"


_GEOIP_NULL = _GeoIPNull()

try:
    import geoip2.database
    import geoip2.errors
    import geoip2.models
    import maxminddb

    # geoip2 >= 2.x builds its model from the raw response mapping; ``{}`` is the
    # empty placeholder (``None`` raised AttributeError as of geoip2 2.9).
    GEOIP_EMPTY_COUNTRY = geoip2.models.Country({})
    GEOIP_EMPTY_CITY = geoip2.models.City({})
except ImportError:
    geoip2 = None
    maxminddb = None
    GEOIP_EMPTY_COUNTRY = _GEOIP_NULL
    GEOIP_EMPTY_CITY = _GEOIP_NULL


def _none_if_null(value: Any) -> Any:
    """Map the geoip2-absent null sentinel to ``None`` for *leaf* values.

    When geoip2 is absent, attribute chains through :data:`_GEOIP_NULL` return
    the *same* sentinel (so intermediate access stays safe to dot through), but a
    leaked sentinel at a scalar leaf breaks the contract: it is ``is not None``,
    not JSON-serialisable, and psycopg cannot adapt it (e.g. ``website.visitor``'s
    ``country_code`` upsert hard-errors for anonymous visitors without geoip2).
    Coerce it to ``None`` at the leaf; a genuine ``0`` / ``0.0`` is preserved.
    """
    return None if value is _GEOIP_NULL else value


# Exception tuples for the ``except`` clauses below. With geoip2/maxminddb absent
# we cannot name their exception classes (evaluating them against ``None`` raises
# AttributeError at except-match time), so fall back to ``OSError`` /
# ``LookupError``.
_GEOIP_DB_ERRORS: tuple[type[BaseException], ...] = (
    (OSError, maxminddb.InvalidDatabaseError) if maxminddb is not None else (OSError,)
)
_GEOIP_NOT_FOUND: type[BaseException] = (
    geoip2.errors.AddressNotFoundError if geoip2 is not None else LookupError
)
# A malformed/missing IP makes geoip2 raise ``ValueError`` (bad address) or
# ``TypeError`` (``self.ip is None``), not ``AddressNotFoundError``. ``self.ip``
# is the attacker-influenceable ``remote_addr``; per the :class:`GeoIP` contract a
# bad address yields an empty record, so catch these and degrade to "no GeoIP"
# rather than 500-ing a page that reads ``geoip.location.time_zone`` unguarded.
_GEOIP_BAD_ADDRESS: tuple[type[BaseException], ...] = (ValueError, TypeError)


class GeoIP(collections.abc.Mapping):
    """
    IP geolocalization utility, determine information such as the
    country or the timezone of the user based on their IP Address.

    The instances share the same API as `geoip2.models.City
    <https://geoip2.readthedocs.io/en/latest/#geoip2.models.City>`_.

    When the IP couldn't be geolocalized (missing database, bad address)
    then an empty object is returned. This empty object can be used like
    a regular one with the exception that all values are set to None.

    :param str ip: The IP Address to geo-localize

    .. note::

        The geoip info for the current request is available at
        :attr:`~odoo.http.request.geoip`.

    .. code-block:: python

        >>> GeoIP("127.0.0.1").country.iso_code
        >>> odoo_ip = socket.gethostbyname("odoo.com")
        >>> GeoIP(odoo_ip).country.iso_code
        'FR'
    """

    def __init__(self, ip: str, app: Any = None) -> None:
        # ``app`` is the :class:`Application` holding the cached GeoIP ``Reader``s.
        # Request injects its own; the lazy fallback keeps standalone constructors
        # (``res.device``, tests) working without the module singleton.
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
        # Determine whether the attribute exists on the country object or
        # on the city object.
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
