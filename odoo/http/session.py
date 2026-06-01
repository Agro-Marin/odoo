import base64
import collections.abc
import contextlib
import os
import re
import time
from collections.abc import Iterable, Iterator
from hashlib import sha512
from pathlib import Path
from typing import Any

from odoo.libs._vendor import sessions
from odoo.libs.json import dumps_bytes as _fast_dumps_bytes
from odoo.libs.json import loads as _fast_loads
from odoo.tools import get_lang
from odoo.tools.json import orjson_default

from .constants import (
    DEFAULT_LANG,
    SESSION_DELETION_TIMER,
    SESSION_LIFETIME,
    STORED_SESSION_BYTES,
    get_default_session,
)

# A generated session id is sha512().digest()[:-1] base64-urlsafe-encoded:
# 63 bytes → 84 chars, no padding (63 is a multiple of 3). The static prefix
# (first STORED_SESSION_BYTES chars) survives soft rotation; the suffix
# (remaining chars) is replaced. Soft rotation requires the static prefix to
# be strictly shorter than the full sid — assert it here so a future change
# to STORED_SESSION_BYTES that breaks rotation fails at import time, not on
# the first concurrent request.
_SESSION_KEY_LENGTH = 84
assert STORED_SESSION_BYTES < _SESSION_KEY_LENGTH, (
    f"STORED_SESSION_BYTES ({STORED_SESSION_BYTES}) must be < "
    f"_SESSION_KEY_LENGTH ({_SESSION_KEY_LENGTH}) for soft rotation to work"
)
_base64_urlsafe_re = re.compile(rf"^[A-Za-z0-9_-]{{{_SESSION_KEY_LENGTH}}}$")
_session_identifier_re = re.compile(rf"^[A-Za-z0-9_-]{{{STORED_SESSION_BYTES}}}$")

# Cap the per-session ``_trace`` device-log list so a session shared across
# many devices/IPs (mobile users on rotating networks) doesn't grow without
# bound. Eviction is LRU by ``last_activity``.
_TRACE_MAX_ENTRIES = 50


class FilesystemSessionStore(sessions.FilesystemSessionStore):
    """Place where to load and save session objects."""

    def get_session_filename(self, sid: str) -> str:
        # scatter sessions across 4096 (64^2) directories
        if not self.is_valid_key(sid):
            raise ValueError(f"Invalid session id {sid!r}")
        return str(Path(self.path, sid[:2], sid))

    def save(self, session: Session) -> None:
        dirname = Path(self.get_session_filename(session.sid)).parent
        if not dirname.is_dir():
            with contextlib.suppress(OSError):
                dirname.mkdir(mode=0o0700)
        super().save(session)

    def delete_old_sessions(self, session: Session) -> None:
        if "gc_previous_sessions" in session:
            if session["create_time"] + SESSION_DELETION_TIMER < time.time():
                # Delete ONLY the pre-rotation files that share the static
                # prefix, keeping the current session file intact. Previously
                # the delete-then-save pattern created a brief window where
                # the current file was gone, letting concurrent requests
                # trigger ``renew_missing`` and silently log the user out.
                self.delete_from_identifiers(
                    [session.sid[:STORED_SESSION_BYTES]],
                    exclude_sid=session.sid,
                )
                del session["gc_previous_sessions"]
                self.save(session)

    def get(self, sid: str) -> Session:
        # retro compatibility
        old_path = Path(super().get_session_filename(sid))
        session_path = Path(self.get_session_filename(sid))
        if old_path.is_file() and not session_path.is_file():
            dirname = session_path.parent
            if not dirname.is_dir():
                with contextlib.suppress(OSError):
                    dirname.mkdir(mode=0o0700)
            with contextlib.suppress(OSError):
                old_path.rename(session_path)
        return super().get(sid)

    def rotate(self, session: Session, env: Any, soft: bool = False) -> None:
        # With a soft rotation, things like the CSRF token will still work. It's used for rotating
        # the session in a way that half the bytes remain to identify the user and the other half
        # to authenticate the user. Meanwhile with a hard rotation the entire session id is changed,
        # which is useful in cases such as logging the user out.
        if soft:
            # Multiple network requests can occur at the same time, all using the old session.
            # We don't want to create a new session for each request, it's better to reference the one already made.
            static = session.sid[:STORED_SESSION_BYTES]
            recent_session = self.get(session.sid)
            if "next_sid" in recent_session:
                # A concurrent request already rotated. Adopt the peer's
                # authoritative session-management metadata (token,
                # create_time, gc marker) so the cookie/token stay
                # consistent for subsequent requests, then flush B's
                # local modifications so they are not lost.
                new_sid = recent_session["next_sid"]
                if session.is_dirty:
                    peer_state = self.get(new_sid)
                    for key in ("session_token", "create_time", "gc_previous_sessions"):
                        if key in peer_state:
                            session[key] = peer_state[key]
                    session.sid = new_sid
                    self.save(session)
                else:
                    session.sid = new_sid
                return
            next_sid = static + self.generate_key()[STORED_SESSION_BYTES:]
        else:
            next_sid = self.generate_key()

        # Compute the new session token BEFORE any destructive operation on disk.
        # If token computation fails (e.g. transient DB error), the session
        # remains untouched so the user stays logged in.
        new_token = None
        if session.uid:
            if not env:
                msg = "Saving an authenticated session requires an environment"
                raise ValueError(msg)
            new_token = (
                env["res.users"].browse(session.uid)._compute_session_token(next_sid)
            )

        if soft:
            session["next_sid"] = next_sid
            session["deletion_time"] = time.time() + SESSION_DELETION_TIMER
            self.save(session)
            session["gc_previous_sessions"] = True
            session.sid = next_sid
            del session["deletion_time"]
            del session["next_sid"]
        else:
            self.delete(session)
            session.sid = next_sid

        # ``_compute_session_token`` can return ``False`` (deleted user,
        # forged uid, or empty field values). ``is not None`` would let
        # that ``False`` through and silently log the user out on the next
        # request. Treat any falsy token as "don't update".
        if new_token:
            session.session_token = new_token
        session.should_rotate = False
        session["create_time"] = time.time()
        self.save(session)

    def vacuum(self, max_lifetime: int = SESSION_LIFETIME) -> None:
        from .application import root  # lazy import

        threshold = time.time() - max_lifetime
        base_path = Path(root.session_store.path)
        for path in base_path.glob("*/*"):
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < threshold:
                    path.unlink()

    def generate_key(self, salt: bytes | None = None) -> str:
        # The generated key is case sensitive (base64) and the length is 84 chars.
        # In the worst-case scenario, i.e. in an insensitive filesystem (NTFS for example)
        # taking into account the proportion of characters in the pool and a length
        # of 42 (stored part in the database), the entropy for the base64 generated key
        # is 217.875 bits which is better than the 160 bits entropy of a hexadecimal key
        # with a length of 40 (method ``generate_key`` of ``SessionStore``).
        # The risk of collision is negligible in practice.
        # Formulas:
        #   - L: length of generated word
        #   - p_char: probability of obtaining the character in the pool
        #   - n: size of the pool
        #   - k: number of generated word
        #   Entropy = - L * sum(p_char * log2(p_char))
        #   Collision ~= (1 - exp((-k * (k - 1)) / (2 * (n**L))))
        key = str(time.time()).encode() + os.urandom(64)
        hash_key = sha512(key).digest()[:-1]  # prevent base64 padding
        return base64.urlsafe_b64encode(hash_key).decode("utf-8")

    def is_valid_key(self, key: str) -> bool:
        return _base64_urlsafe_re.match(key) is not None

    def get_missing_session_identifiers(self, identifiers: Iterable[str]) -> set[str]:
        """
        :param identifiers: session identifiers whose file existence must be checked
                            identifiers are a part session sid (first 42 chars)
        :type identifiers: iterable
        :return: the identifiers which are not present on the filesystem
        :rtype: set
        """
        # There are a lot of session files.
        # Use the param ``identifiers`` to select the necessary directories.
        # In the worst case, we have 4096 directories (64^2).
        identifiers = set(identifiers)
        base = Path(self.path)
        directories = {str(base / identifier[:2]) for identifier in identifiers}
        # Remove the identifiers for which a file is present on the filesystem.
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
            # Avoid to remove a session if it does not match an identifier.
            # This prevent malicious user to delete sessions from a different
            # database by specifying a custom ``res.device.log``.
            if not _session_identifier_re.match(identifier):
                msg = "Identifier format incorrect, did you pass in a string instead of a list?"
                raise ValueError(msg)
            parent_dir = base_path / identifier[:2]
            # Defense-in-depth: the regex above already restricts ``identifier``
            # to ``[A-Za-z0-9_-]`` so ``identifier[:2]`` cannot escape the
            # filestore — but we re-check the constructed path anyway, in case
            # the regex is later loosened or ``base_path`` is symlinked.
            if parent_dir.is_relative_to(base_path):
                files_to_unlink.extend(parent_dir.glob(identifier + "*"))
        for fn in files_to_unlink:
            if exclude_sid is not None and fn.name == exclude_sid:
                continue
            with contextlib.suppress(OSError):
                fn.unlink()


# JSON-native types that survive a round-trip through the session file
# WITHOUT silent coercion.  ``tuple`` is intentionally NOT in this set:
# tuples become lists in JSON, and the test contract treats that as a
# "not recommended" case (allowed, but the round-trip yields a list, so
# callers must re-tuple if they need tuple semantics).
_SESSION_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _coerce_session_value(value: Any) -> Any:
    """Recursively validate and coerce ``value`` for session storage.

    Returns the (possibly coerced) value if it is representable as JSON.
    Raises ``TypeError`` for anything else — see ``Session.__setitem__``
    for the rationale.

    ``bool`` is checked BEFORE ``int`` because ``isinstance(True, int)``
    is ``True`` in Python and we want bools to short-circuit cleanly to
    the primitive branch (the reverse order would still work, but the
    explicit ordering documents the intent).
    """
    if isinstance(value, _SESSION_JSON_PRIMITIVES):
        return value
    if isinstance(value, dict):
        # Validate keys are strings (JSON object keys must be strings),
        # then recurse on values.
        coerced = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(
                    f"Session dict keys must be str, got {type(k).__name__}: {k!r}"
                )
            coerced[k] = _coerce_session_value(v)
        return coerced
    if isinstance(value, (list, tuple)):
        # tuple → list coercion is the "not recommended" case from the
        # test contract: allowed, but the user gets a list back.
        return [_coerce_session_value(v) for v in value]
    raise TypeError(
        f"Session values must be JSON-serializable "
        f"(str/int/float/bool/None/list/dict/tuple), "
        f"got {type(value).__name__}: {value!r}"
    )


class Session(collections.abc.MutableMapping):
    """Structure containing data persisted across requests.

    The session tracks modifications through ``__setitem__`` only.
    Mutating a nested value in place (e.g. ``session.context['lang'] =
    'es_MX'``) does not mark the session dirty and the change will not
    be persisted. After such mutations, call :meth:`touch` explicitly or
    reassign the top-level key.
    """

    __slots__ = (
        "_Session__data",
        "can_save",
        "is_dirty",
        "is_new",
        "should_rotate",
        "sid",
    )

    def __init__(self, data: dict[str, Any], sid: str, new: bool = False) -> None:
        self.can_save: bool = True
        self.__data: dict[str, Any] = {}
        self.update(data)
        self.is_dirty: bool = False
        self.is_new: bool = new
        self.should_rotate: bool = False
        self.sid: str = sid

    def __getitem__(self, item: str) -> Any:
        return self.__data[item]

    def __setitem__(self, item: str, value: Any) -> None:
        """Store ``value`` under ``item`` and mark the session dirty.

        Sessions persist as JSON files, so values must be representable
        in JSON.  This setter VALIDATES the value structure and rejects
        anything that would round-trip lossily:

        * ``str, int, float, bool, None``    → stored as-is
        * ``list, dict``                     → recursively validated
        * ``tuple``                          → coerced to ``list`` (lossy
                                               but JSON-natively supported,
                                               so accepted with type
                                               coercion silently performed)
        * Anything else                      → ``TypeError`` raised

        The strict validation differs from the lenient ``orjson_default``
        used by HTTP responses and ``fields.Json``: those callers cannot
        reject values mid-render, so they fall back to ``str(obj)``.  A
        session lives across requests, and silently storing
        ``datetime.datetime.now()`` as the string ``"2026-05-09 19:23:02"``
        bites callers months later when they read the value back and find a
        string where they expected a datetime.  Reject loudly at write
        time instead — the caller picks the right representation
        explicitly (e.g. ``session["foo"] = some_dt.isoformat()``).

        Mutating a nested value in place (e.g. ``session.context['lang'] =
        'es_MX'``) does NOT trigger this method and will not be persisted
        unless ``self.touch()`` is called or ``self.should_rotate`` is set.

        :raises TypeError: if ``value`` (or any nested element of a list/
            dict/tuple) is not JSON-serializable.
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

    #
    # Session properties
    #
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
    def debug(self) -> str | None:
        return self.get("debug")

    @debug.setter
    def debug(self, debug: str | None) -> None:
        self["debug"] = debug

    @property
    def session_token(self) -> str | None:
        return self.get("session_token")

    @session_token.setter
    def session_token(self, session_token: str | None) -> None:
        self["session_token"] = session_token

    #
    # Session methods
    #
    def authenticate(self, env: Any, credential: dict[str, Any]) -> dict[str, Any]:
        """
        Authenticate the current user with the given db, login and
        credential. If successful, store the authentication parameters in
        the current session, unless multi-factor-auth (MFA) is
        activated. In that case, that last part will be done by
        :ref:`finalize`.

        .. versionchanged:: saas-15.3
           The current request is no longer updated using the user and
           context of the session when the authentication is done using
           a database different than request.db. It is up to the caller
           to open a new cursor/registry/env on the given database.
        """
        from . import request  # lazy import

        wsgienv = {
            "interactive": True,
            "base_location": request.httprequest.url_root.rstrip("/"),
            "HTTP_HOST": request.httprequest.environ["HTTP_HOST"],
            "REMOTE_ADDR": request.httprequest.environ["REMOTE_ADDR"],
        }
        env = env(user=None, su=False)
        auth_info = env["res.users"].authenticate(credential, wsgienv)
        pre_uid = auth_info["uid"]

        self.uid = None
        self["pre_login"] = credential["login"]
        self["pre_uid"] = pre_uid

        # if 2FA is disabled we finalize immediately
        user = env["res.users"].browse(pre_uid)
        if auth_info.get("mfa") == "skip" or not user._mfa_url():
            self.finalize(env)

        if request and request.session is self and request.db == env.registry.db_name:
            request.env = env(user=self.uid, context=self.context)
            request.update_context(lang=get_lang(request.env(user=pre_uid)).code)

        return auth_info

    def finalize(self, env: Any) -> None:
        """
        Finalizes a partial session, should be called on MFA validation
        to convert a partial / pre-session into a logged-in one.
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
        from . import request  # lazy import

        db = self.db if keep_db else get_default_session()["db"]  # None
        debug = self.debug
        self.clear()
        self.update(get_default_session(), db=db, debug=debug)
        self.context["lang"] = request.default_lang() if request else DEFAULT_LANG
        self.should_rotate = True

        if request and request.env:
            request.env["ir.http"]._post_logout()

    def touch(self) -> None:
        self.is_dirty = True

    def update_trace(self, request: Any) -> dict[str, Any] | None:
        """
        :return: dict if a device log has to be inserted, ``None`` otherwise
        """
        if self.get("_trace_disable"):
            # To avoid generating useless logs, e.g. for automated technical sessions,
            # a session can be flagged with `_trace_disable`. This should never be done
            # without a proper assessment of the consequences for auditability.
            # Non-admin users have no direct or indirect way to set this flag, so it can't
            # be abused by unprivileged users. Such sessions will of course still be
            # subject to all other auditing mechanisms (server logs, web proxy logs,
            # metadata tracking on modified records, etc.)
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
                # If the device logs are not up to date (i.e. not updated for one hour or more)
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
        from .application import root  # lazy import

        root.session_store.delete_old_sessions(self)
