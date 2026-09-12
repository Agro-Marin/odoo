from html.parser import HTMLParser
from threading import RLock

import geoip2.errors
import geoip2.models

from odoo.http import FilesystemSessionStore
from odoo.http.exceptions import SessionExpiredException

TEST_IP = "192.0.2.42"
TEST_IP_GEOIP_CITY = geoip2.models.City(
    ["en"],
    continent={
        "code": "EU",
        "geoname_id": 6255148,
        "names": {
            "de": "Europa",
            "en": "Europe",
            "es": "Europa",
            "fr": "Europe",
            "ja": "ヨーロッパ",
            "pt-BR": "Europa",
            "ru": "Европа",
            "zh-CN": "欧洲",
        },
    },
    country={
        "geoname_id": 3017382,
        "is_in_european_union": True,
        "iso_code": "FR",
        "names": {
            "de": "Frankreich",
            "en": "France",
            "es": "Francia",
            "fr": "France",
            "ja": "フランス共和国",
            "pt-BR": "França",
            "ru": "Франция",
            "zh-CN": "法国",
        },
    },
    location={
        "accuracy_radius": 500,
        "latitude": 48.8582,
        "longitude": 2.3387,
        "time_zone": "Europe/Paris",
    },
    registered_country={
        "geoname_id": 3017382,
        "is_in_european_union": True,
        "iso_code": "FR",
        "names": {
            "de": "Frankreich",
            "en": "France",
            "es": "Francia",
            "fr": "France",
            "ja": "フランス共和国",
            "pt-BR": "França",
            "ru": "Франция",
            "zh-CN": "法国",
        },
    },
    traits={"ip_address": TEST_IP, "prefix_len": 21},
)
TEST_IP_GEOIP_COUNTRY = geoip2.models.Country(
    ["en"],
    continent={
        "code": "EU",
        "geoname_id": 6255148,
        "names": {
            "de": "Europa",
            "en": "Europe",
            "es": "Europa",
            "fr": "Europe",
            "ja": "ヨーロッパ",
            "pt-BR": "Europa",
            "ru": "Европа",
            "zh-CN": "欧洲",
        },
    },
    country={
        "geoname_id": 3017382,
        "is_in_european_union": True,
        "iso_code": "FR",
        "names": {
            "de": "Frankreich",
            "en": "France",
            "es": "Francia",
            "fr": "France",
            "ja": "フランス共和国",
            "pt-BR": "França",
            "ru": "Франция",
            "zh-CN": "法国",
        },
    },
    registered_country={
        "geoname_id": 3017382,
        "is_in_european_union": True,
        "iso_code": "FR",
        "names": {
            "de": "Frankreich",
            "en": "France",
            "es": "Francia",
            "fr": "France",
            "ja": "フランス共和国",
            "pt-BR": "França",
            "ru": "Франция",
            "zh-CN": "法国",
        },
    },
    traits={"ip_address": TEST_IP, "prefix_len": 21},
)
USER_AGENT_linux_chrome = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
USER_AGENT_linux_firefox = (
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0"
)
USER_AGENT_android_chrome = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36"


class MemoryGeoipResolver:
    def __init__(self):
        self.country_db = {TEST_IP: TEST_IP_GEOIP_COUNTRY}
        self.city_db = {TEST_IP: TEST_IP_GEOIP_CITY}

    def country(self, ip):
        record = self.country_db.get(ip)
        if not record:
            raise geoip2.errors.AddressNotFoundError(ip)
        return record

    def city(self, ip):
        record = self.city_db.get(ip)
        if not record:
            raise geoip2.errors.AddressNotFoundError(ip)
        return record


class MemorySessionStore(FilesystemSessionStore):
    def __init__(self, session_class, renew_missing=False):
        super().__init__(
            path="", session_class=session_class, renew_missing=renew_missing
        )
        self.store = {}
        self._lock = RLock()

    def _locked_sid(self, sid):
        self.get_session_filename(sid)
        return self._lock

    def get(self, sid):
        with self._lock:
            session = self.store.get(sid)
            return session.snapshot() if session is not None else self.new()

    def _save_unlocked(self, session):
        with self._lock:
            session.is_new = False
            session.mark_clean()
            stored = session.snapshot()
            stored.rotation = None
            stored.should_rotate = False
            self.store[session.sid] = stored

    def keep_alive(self, session):
        with self._lock:
            if session.is_new:
                self.save(session)
            elif session.sid not in self.store:
                raise SessionExpiredException("Session was revoked")

    def delete(self, session):
        self.store.pop(session.sid, None)

    def _remove_sid(self, sid):
        self.store.pop(sid, None)

    def remove_sessions_for_identifiers(self, identifiers, exclude_sid=None):
        sid_to_remove = [
            sid
            for sid in self.store
            if sid != exclude_sid
            and any(sid.startswith(identifier) for identifier in identifiers)
        ]
        for sid in sid_to_remove:
            self.store.pop(sid)

    def get_missing_session_identifiers(self, identifiers):
        return {
            identifier
            for identifier in identifiers
            if not any(sid.startswith(identifier) for sid in self.store)
        }

    def vacuum(self):
        return


class HtmlTokenizer(HTMLParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tokens = []

    @classmethod
    def _attrs_to_str(cls, attrs):
        out = []
        for key, value in attrs:
            out.append(f"{key}={value!r}" if value else key)
        return " ".join(out)

    def handle_starttag(self, tag, attrs):
        self.tokens.append(f"<{tag} {self._attrs_to_str(attrs)}>")

    def handle_endtag(self, tag):
        self.tokens.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        data = data.strip()
        if data:
            self.tokens.append(data)

    @classmethod
    def tokenize(cls, source_str):
        tokenizer = cls()
        tokenizer.feed(source_str)
        return tokenizer.tokens
