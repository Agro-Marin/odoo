import base64
import collections.abc
import contextlib
import os
import re
import time
from collections.abc import Iterable, Iterator
from hashlib import sha512
from pathlib import Path
from stat import S_ISREG
from typing import Any

from odoo.libs._vendor import sessions
from odoo.libs.json import dumps_bytes as _dumps_bytes
from odoo.tools import get_lang

from .constants import (
    DEFAULT_LANG,
    SESSION_DELETION_TIMER,
    SESSION_LIFETIME,
    STORED_SESSION_BYTES,
    get_default_session,
)
from .core import request

_SESSION_KEY_LENGTH = 84
assert STORED_SESSION_BYTES < _SESSION_KEY_LENGTH, (
    f"STORED_SESSION_BYTES ({STORED_SESSION_BYTES}) must be < "
    f"_SESSION_KEY_LENGTH ({_SESSION_KEY_LENGTH}) for soft rotation to work"
)
_base64_urlsafe_re = re.compile(rf"^[A-Za-z0-9_-]{{{_SESSION_KEY_LENGTH}}}$")
_session_identifier_re = re.compile(rf"^[A-Za-z0-9_-]{{{STORED_SESSION_BYTES}}}$")

_TRACE_MAX_ENTRIES = 50

_MTIME_REFRESH_INTERVAL = 24 * 60 * 60


class FilesystemSessionStore(sessions.FilesystemSessionStore):
    """Place where to load and save session objects."""

    def get_session_filename(self, sid: str) -> str:
        if not self.is_valid_key(sid):
            raise ValueError(f"Invalid session id {sid!r}")
        return str(Path(self.path, sid[:2], sid))

    def save(self, session: Session) -> None:
        dirname = Path(self.get_session_filename(session.sid)).parent
        if not dirname.is_dir():
            with contextlib.suppress(OSError):
                dirname.mkdir(mode=0o0700)
        super().save(session)

    def new(self) -> Session:
        session = super().new()
        session.store = self
        return session

    def get(self, sid: str) -> Session:
        session = super().get(sid)
        session.store = self
        if not session.is_new:
            with contextlib.suppress(OSError):
                path = Path(self.get_session_filename(session.sid))
                if path.stat().st_mtime < time.time() - _MTIME_REFRESH_INTERVAL:
                    os.utime(path)
        return session

    def _delete_sid(self, sid: str) -> None:
        """Delete one session file by sid.

        Used to drop the pre-rotation file *after* the new one is written (see
        :meth:`rotate`); unlike :meth:`delete` it takes a sid rather than the
        live session, whose ``sid`` has already advanced to the new value.
        """
        with contextlib.suppress(OSError, ValueError):
            Path(self.get_session_filename(sid)).unlink()

    def keep_alive(self, session: Session) -> None:
        """Refresh the session file's mtime without rewriting its contents.

        ``vacuum`` reaps by mtime, so "extend this session's lifetime" -- what
        :meth:`Session.touch` asks for, and what several core controllers call it
        for (``/odoo``, ``/web/session/get_session_info``) -- needs nothing more
        than an ``utime``. Routing it through :meth:`save` instead cost a full
        atomic rewrite (``mkstemp`` + ``fchmod`` + write + **fsync** + rename) of
        byte-identical content on *every* such request: ~1.2 ms of blocking IO on
        local NVMe, far worse on the network filestores the store is written for.

        This is the write-path counterpart of the lazy refresh :meth:`get`
        already does on read past :data:`_MTIME_REFRESH_INTERVAL`.

        Falls back to a real save when the file is not there yet: a brand-new
        session's first ``touch()`` (``Request.csrf_token``) is exactly what
        persists it, and there is no mtime to bump.
        """
        try:
            os.utime(self.get_session_filename(session.sid))
        except OSError:
            self.save(session)

    def delete_old_sessions(self, session: Session) -> None:
        if "gc_previous_sessions" in session:
            if session["create_time"] + SESSION_DELETION_TIMER < time.time():
                self.delete_from_identifiers(
                    [session.sid[:STORED_SESSION_BYTES]],
                    exclude_sid=session.sid,
                )
                del session["gc_previous_sessions"]
                self.save(session)

    def rotate(self, session: Session, env: Any, soft: bool = False) -> None:
        if soft:
            static = session.sid[:STORED_SESSION_BYTES]
            recent_session = self.get(session.sid)
            if "next_sid" in recent_session:
                new_sid = recent_session["next_sid"]
                peer_state = self.get(new_sid)
                if peer_state.is_new:
                    if session.is_modified():
                        self.save(session)
                    return
                if session.is_modified():
                    for key in ("next_sid", "deletion_time"):
                        if key in session:
                            del session[key]
                    for key in ("session_token", "create_time", "gc_previous_sessions"):
                        if key in peer_state:
                            session[key] = peer_state[key]
                    session.sid = new_sid
                    self.save(session)
                else:
                    session.sid = new_sid
                session.should_rotate = False
                return
            next_sid = static + self.generate_key()[STORED_SESSION_BYTES:]
        else:
            next_sid = self.generate_key()

        new_token = None
        if session.uid:
            if env is None:
                msg = "Saving an authenticated session requires an environment"
                raise ValueError(msg)
            new_token = (
                env["res.users"].browse(session.uid)._compute_session_token(next_sid)
            )

        old_sid_to_delete = None
        if soft:
            session["next_sid"] = next_sid
            session["deletion_time"] = time.time() + SESSION_DELETION_TIMER
            self.save(session)
            session["gc_previous_sessions"] = True
            session.sid = next_sid
            del session["deletion_time"]
            del session["next_sid"]
        else:
            # Hard rotation: switch to the new sid but KEEP the old file until
            # the new one is safely written (below). Deleting it first meant a
            # crash or a failed save destroyed the session outright, and a
            # concurrent request still carrying the old cookie fell through to
            # ``renew_missing`` and clobbered the fresh cookie (B3).
            old_sid_to_delete = session.sid
            session.sid = next_sid

        if new_token:
            session.session_token = new_token
        session.should_rotate = False
        session["create_time"] = time.time()
        self.save(session)  # writes the NEW file; raises on failure (B4)

        if old_sid_to_delete is not None:
            # Only now that the new file exists is it safe to drop the old one.
            self._delete_sid(old_sid_to_delete)

    def vacuum(self, max_lifetime: int = SESSION_LIFETIME) -> None:
        threshold = time.time() - max_lifetime
        base_path = Path(self.path)
        for path in base_path.glob("*/*"):
            with contextlib.suppress(OSError):
                st = path.stat()
                if S_ISREG(st.st_mode) and st.st_mtime < threshold:
                    path.unlink()
        for path in base_path.glob(f"*{sessions._fs_transaction_suffix}"):
            with contextlib.suppress(OSError):
                st = path.stat()
                if S_ISREG(st.st_mode) and st.st_mtime < threshold:
                    path.unlink()

    def generate_key(self, salt: bytes | None = None) -> str:
        key = str(time.time()).encode() + os.urandom(64)
        hash_key = sha512(key).digest()[:-1]
        return base64.urlsafe_b64encode(hash_key).decode("utf-8")

    def is_valid_key(self, key: str) -> bool:
        return _base64_urlsafe_re.match(key) is not None

    def get_missing_session_identifiers(self, identifiers: Iterable[str]) -> set[str]:
        """Return the identifiers with no session file on the filesystem.

        :param identifiers: session identifiers whose file existence must be checked
                            each is the first 42 chars of a session sid
        :type identifiers: iterable
        :return: the identifiers which are not present on the filesystem
        :rtype: set
        """
        identifiers = set(identifiers)
        base = Path(self.path)
        directories = {str(base / identifier[:2]) for identifier in identifiers}
        for directory in directories:
            with (
                contextlib.suppress(OSError),
                os.scandir(directory) as session_files,
            ):
                identifiers.difference_update(
                    sf.name[:STORED_SESSION_BYTES] for sf in session_files
                )
        return identifiers

    def delete_from_identifiers(
        self,
        identifiers: list[str],
        exclude_sid: str | None = None,
    ) -> None:
        """Delete session files matching the given identifiers.

        :param exclude_sid: optional full session id whose file MUST be
            kept even if it shares the static prefix of one of the
            ``identifiers``. Used by :meth:`delete_old_sessions` to
            avoid deleting the current session file alongside its
            rotated-away predecessors.
        """
        files_to_unlink: list[Path] = []
        base_path = Path(self.path)
        for identifier in identifiers:
            if not _session_identifier_re.match(identifier):
                msg = "Identifier format incorrect, did you pass in a string instead of a list?"
                raise ValueError(msg)
            parent_dir = base_path / identifier[:2]
            if parent_dir.is_relative_to(base_path):
                files_to_unlink.extend(parent_dir.glob(identifier + "*"))
        for fn in files_to_unlink:
            if exclude_sid is not None and fn.name == exclude_sid:
                continue
            with contextlib.suppress(OSError):
                fn.unlink()


_SESSION_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _coerce_session_value(value: Any) -> Any:
    """Recursively validate and coerce ``value`` for session storage.

    Returns the (possibly coerced) JSON-representable value, else raises
    ``TypeError`` (see ``Session.__setitem__`` for the rationale).
    """
    if isinstance(value, _SESSION_JSON_PRIMITIVES):
        return value
    if isinstance(value, dict):
        coerced = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(
                    f"Session dict keys must be str, got {type(k).__name__}: {k!r}"
                )
            coerced[k] = _coerce_session_value(v)
        return coerced
    if isinstance(value, (list, tuple)):
        return [_coerce_session_value(v) for v in value]
    raise TypeError(
        f"Session values must be JSON-serializable "
        f"(str/int/float/bool/None/list/dict/tuple), "
        f"got {type(value).__name__}: {value!r}"
    )


class Session(collections.abc.MutableMapping):
    """Structure containing data persisted across requests.

    Change-tracking is twofold. Explicit writes (``__setitem__``, ``__delitem__``,
    ``clear``, :meth:`touch`) set :attr:`is_dirty` eagerly. On top of that,
    :meth:`is_modified` detects *in-place* mutation of a nested value
    (``session.context['lang'] = 'es_MX'``) — which bypasses ``__setitem__`` — by
    diffing the data against a per-request baseline captured by :meth:`mark_clean`.
    The request lifecycle calls :meth:`mark_clean` after load and gates
    persistence on :meth:`is_modified`, so callers no longer need a defensive
    :meth:`touch` after mutating a nested value.
    """

    __slots__ = (
        "_Session__baseline",
        "_Session__data",
        "can_save",
        "is_dirty",
        "is_new",
        "should_rotate",
        "sid",
        "store",
    )

    def __init__(self, data: dict[str, Any], sid: str, new: bool = False) -> None:
        self.can_save: bool = True
        self.__data: dict[str, Any] = dict(data)
        self.is_dirty: bool = False
        self.__baseline: bytes | None = None
        self.is_new: bool = new
        self.should_rotate: bool = False
        self.sid: str = sid
        self.store: Any = None

    def __getitem__(self, item: str) -> Any:
        return self.__data[item]

    def __setitem__(self, item: str, value: Any) -> None:
        """Store ``value`` under ``item`` and mark the session dirty.

        Sessions persist as JSON, so values must round-trip without loss:
        str/int/float/bool/None and (recursively) list/dict are stored as-is,
        ``tuple`` is coerced to ``list``, anything else raises ``TypeError``.

        Stricter than the lenient ``orjson_default`` used by HTTP responses:
        those fall back to ``str(obj)`` mid-render, but a session lives across
        requests, so silently storing a ``datetime`` as a string bites callers
        later. Reject loudly so the caller picks the representation (e.g.
        ``session["foo"] = some_dt.isoformat()``). In-place mutation of a nested
        value bypasses this validation; :meth:`is_modified` still flags the
        change via the per-request baseline.

        :raises TypeError: if ``value`` (or a nested element) is not
            JSON-serializable.
        """
        value = _coerce_session_value(value)
        if item not in self.__data or self.__data[item] != value:
            self.is_dirty = True
        self.__data[item] = value

    def __delitem__(self, item: str) -> None:
        del self.__data[item]
        self.is_dirty = True

    def __len__(self) -> int:
        return len(self.__data)

    def __iter__(self) -> Iterator[str]:
        return iter(self.__data)

    def clear(self) -> None:
        self.__data.clear()
        self.is_dirty = True

    @property
    def uid(self) -> int | None:
        return self.get("uid")

    @uid.setter
    def uid(self, uid: int | None) -> None:
        self["uid"] = uid

    @property
    def db(self) -> str | None:
        return self.get("db")

    @db.setter
    def db(self, db: str | None) -> None:
        self["db"] = db

    @property
    def login(self) -> str | None:
        return self.get("login")

    @login.setter
    def login(self, login: str | None) -> None:
        self["login"] = login

    @property
    def context(self) -> dict[str, Any] | None:
        return self.get("context")

    @context.setter
    def context(self, context: dict[str, Any] | None) -> None:
        self["context"] = context

    @property
    def debug(self) -> str:
        return self.get("debug") or ""

    @debug.setter
    def debug(self, debug: str | None) -> None:
        self["debug"] = debug

    @property
    def session_token(self) -> str | None:
        return self.get("session_token")

    @session_token.setter
    def session_token(self, session_token: str | None) -> None:
        self["session_token"] = session_token

    def authenticate(self, env: Any, credential: dict[str, Any]) -> dict[str, Any]:
        """
        Authenticate the current user with the given db, login and
        credential. If successful, store the authentication parameters in
        the current session, unless multi-factor-auth (MFA) is
        activated. In that case, that last part will be done by
        :meth:`finalize`.

        .. versionchanged:: saas-15.3
           The current request is no longer updated using the user and
           context of the session when the authentication is done using
           a database different than request.db. It is up to the caller
           to open a new cursor/registry/env on the given database.
        """
        wsgienv = {
            "interactive": True,
            "base_location": request.httprequest.url_root.rstrip("/"),
            "HTTP_HOST": request.httprequest.environ.get("HTTP_HOST", ""),
            "REMOTE_ADDR": request.httprequest.environ.get("REMOTE_ADDR", ""),
        }
        env = env(user=None, su=False)
        auth_info = env["res.users"].authenticate(credential, wsgienv)
        pre_uid = auth_info["uid"]

        self.uid = None
        self["pre_login"] = credential["login"]
        self["pre_uid"] = pre_uid

        user = env["res.users"].browse(pre_uid)
        if auth_info.get("mfa") == "skip" or not user._mfa_url():
            self.finalize(env)

        if request and request.session is self and request.db == env.registry.db_name:
            request.env = env(user=self.uid, context=self.context)
            request.update_context(lang=get_lang(request.env(user=pre_uid)).code)

        return auth_info

    def finalize(self, env: Any) -> None:
        """
        Finalize a partial session; called on MFA validation to convert a
        partial / pre-session into a logged-in one.
        """
        login = self.pop("pre_login")
        uid = self.pop("pre_uid")

        env = env(user=uid)
        user_context = dict(env["res.users"].context_get())

        self.should_rotate = True
        self.update(
            {
                "db": env.registry.db_name,
                "login": login,
                "uid": uid,
                "context": user_context,
                "session_token": env.user._compute_session_token(self.sid),
            }
        )

    def logout(self, keep_db: bool = False) -> None:
        db = self.db if keep_db else None
        debug = self.debug
        self.clear()
        self.update(get_default_session(), db=db, debug=debug)
        self.context["lang"] = request.default_lang() if request else DEFAULT_LANG
        self.should_rotate = True

        if request and request.env is not None:
            request.env["ir.http"]._post_logout()

    def touch(self) -> None:
        self.is_dirty = True

    def mark_clean(self) -> None:
        """Reset the dirty flag and re-baseline for nested-mutation detection.

        Called once per request after the framework's own session setup (see
        ``Request._get_session_and_dbname``), so that subsequent *application*
        changes — including in-place mutation of a nested value such as
        ``session.context['lang'] = 'es'`` that bypasses :meth:`__setitem__` —
        are picked up by :meth:`is_modified` even if the caller forgets
        :meth:`touch`. The snapshot is an orjson dump of the (JSON-native by
        :meth:`__setitem__`'s contract) session data — ~6x cheaper than the
        ``copy.deepcopy`` it replaces, measured on a representative session.
        """
        self.is_dirty = False
        self.__baseline = _dumps_bytes(self.__data)

    def has_content_changed(self) -> bool:
        """Whether the stored *data* differs from the last :meth:`mark_clean`.

        The question :meth:`is_modified` cannot answer on its own: it also
        reports ``True`` for a bare :meth:`touch`, which asks to extend the
        session's lifetime rather than to rewrite it (see
        :meth:`FilesystemSessionStore.keep_alive`). Only a content change needs
        the file rewritten.

        Detects in-place mutation of nested values that bypass
        :meth:`__setitem__`. Before the first :meth:`mark_clean` (no baseline
        yet) it falls back to :attr:`is_dirty`. The byte comparison can yield a
        false *positive* for a semantically equal dict serialized differently
        (key re-insertion changing order, ``1`` rewritten as ``1.0``); the cost
        is one spurious session save, never a missed one.
        """
        if self.__baseline is None:
            return self.is_dirty
        return _dumps_bytes(self.__data) != self.__baseline

    def is_modified(self) -> bool:
        """Whether the session changed since the last :meth:`mark_clean`.

        ``True`` for explicit writes (via :attr:`is_dirty`) *and* for in-place
        mutation of nested values that bypass :meth:`__setitem__`. Before the
        first :meth:`mark_clean` (no baseline yet) it falls back to
        :attr:`is_dirty`. The byte comparison can yield a false *positive* for
        a semantically equal dict serialized differently (key re-insertion
        changing order, ``1`` rewritten as ``1.0``); the cost is one spurious
        session save, never a missed one.
        """
        return self.is_dirty or self.has_content_changed()

    def update_trace(self, request: Any) -> dict[str, Any] | None:
        """Record the request's device (platform, browser, IP) in the session trace.

        A known device is refreshed at most hourly; a new one is appended,
        evicting the least recently active entry past ``_TRACE_MAX_ENTRIES``.

        :return: dict if a device log has to be inserted, ``None`` otherwise
        """
        if self.get("_trace_disable"):
            return None

        user_agent = request.httprequest.user_agent
        platform = user_agent.platform
        browser = user_agent.browser
        ip_address = request.httprequest.remote_addr
        now = int(time.time())
        for trace in self["_trace"]:
            if (
                trace["platform"] == platform
                and trace["browser"] == browser
                and trace["ip_address"] == ip_address
            ):
                if now - trace["last_activity"] >= 3600:
                    trace["last_activity"] = now
                    self.is_dirty = True
                    return trace
                return None
        new_trace = {
            "platform": platform,
            "browser": browser,
            "ip_address": ip_address,
            "first_activity": now,
            "last_activity": now,
        }
        self["_trace"].append(new_trace)
        if len(self["_trace"]) > _TRACE_MAX_ENTRIES:
            oldest_idx = min(
                range(len(self["_trace"])),
                key=lambda i: self["_trace"][i]["last_activity"],
            )
            del self["_trace"][oldest_idx]
        self.is_dirty = True
        return new_trace

    def _delete_old_sessions(self) -> None:
        """Reap the pre-rotation files this session left behind.

        Dispatched to the store this session was LOADED from, not the global
        ``root.session_store``. Reaching for the singleton meant a session from
        store A garbage-collected against store B — the same defect already
        fixed in :meth:`FilesystemSessionStore.vacuum` (which used to read
        ``root.session_store.path`` instead of ``self.path``), and the last
        global reach-in on the session path now that ``Request`` and ``GeoIP``
        take their collaborators by injection. It also drops a
        ``session -> application`` import cycle that needed a lazy import.
        """
        if self.store is None:
            return
        self.store.delete_old_sessions(self)
