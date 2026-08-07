import collections.abc
import functools
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


class _GeoIPNull:
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

    GEOIP_EMPTY_COUNTRY = geoip2.models.Country({})
    GEOIP_EMPTY_CITY = geoip2.models.City({})
except ImportError:
    geoip2 = None
    maxminddb = None
    GEOIP_EMPTY_COUNTRY = _GEOIP_NULL
    GEOIP_EMPTY_CITY = _GEOIP_NULL


def _none_if_null(value: Any) -> Any:
    return None if value is _GEOIP_NULL else value


_GEOIP_DB_ERRORS: tuple[type[BaseException], ...] = (
    (OSError, maxminddb.InvalidDatabaseError) if maxminddb is not None else (OSError,)
)
_GEOIP_NOT_FOUND: type[BaseException] = (
    geoip2.errors.AddressNotFoundError if geoip2 is not None else LookupError
)
_GEOIP_BAD_ADDRESS: tuple[type[BaseException], ...] = (ValueError, TypeError)

_GEOIP_COUNTRY_MODEL_ATTRS = frozenset(
    {
        "continent",
        "country",
        "maxmind",
        "registered_country",
        "represented_country",
        "traits",
    }
)
_GEOIP_CITY_ONLY_MODEL_ATTRS = frozenset({"city", "location", "postal", "subdivisions"})


class GeoIP(collections.abc.Mapping):
    def __init__(self, ip: str | None, app: Any) -> None:
        self.app = app
        self.ip = ip

    @functools.cached_property
    def _city_record(self):
        root = self.app

        city_db = root.geoip_city_db
        if city_db is None:
            return GEOIP_EMPTY_CITY
        try:
            return city_db.city(self.ip)
        except _GEOIP_DB_ERRORS:
            return GEOIP_EMPTY_CITY
        except _GEOIP_NOT_FOUND:
            return GEOIP_EMPTY_CITY
        except _GEOIP_BAD_ADDRESS:
            return GEOIP_EMPTY_CITY

    @functools.cached_property
    def _country_record(self):
        root = self.app

        if "_city_record" in vars(self):
            return self._city_record
        country_db = root.geoip_country_db
        if country_db is None:
            return self._city_record
        try:
            return country_db.country(self.ip)
        except _GEOIP_DB_ERRORS:
            return self._city_record
        except _GEOIP_NOT_FOUND:
            return GEOIP_EMPTY_COUNTRY
        except _GEOIP_BAD_ADDRESS:
            return GEOIP_EMPTY_COUNTRY

    @property
    def country_name(self) -> str | None:
        return _none_if_null(self.country.name or self.continent.name)

    @property
    def country_code(self) -> str | None:
        return _none_if_null(self.country.iso_code or self.continent.code)

    def __getattr__(self, attr: str) -> Any:
        if geoip2 is None:
            if attr in _GEOIP_COUNTRY_MODEL_ATTRS:
                return getattr(self._country_record, attr)
            if attr in _GEOIP_CITY_ONLY_MODEL_ATTRS:
                return getattr(self._city_record, attr)
            raise AttributeError(f"{self} has no attribute {attr!r}")
        if hasattr(GEOIP_EMPTY_COUNTRY, attr):
            return getattr(self._country_record, attr)
        if hasattr(GEOIP_EMPTY_CITY, attr):
            return getattr(self._city_record, attr)
        raise AttributeError(f"{self} has no attribute {attr!r}")

    def __bool__(self) -> bool:
        return bool(self.country_name)

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
