
import logging
import os
import pathlib
import re
import tempfile
from hashlib import sha1
from os import path
from os import replace as rename
from time import time

from werkzeug.datastructures import CallbackDict

from odoo.libs.json import dumps_bytes as _json_dumps
from odoo.libs.json import loads as _json_loads

_logger = logging.getLogger(__name__)
_sha1_re = re.compile(r"^[a-f0-9]{40}$")


def generate_key(salt=None):
    if salt is None:
        salt = repr(salt).encode("ascii")
    return sha1(
        b"".join([salt, str(time()).encode("ascii"), os.urandom(30)])
    ).hexdigest()


class ModificationTrackingDict(CallbackDict):
    __slots__ = ("modified", "on_update")

    def __init__(self, *args, **kwargs):
        def on_update(self):
            self.modified = True

        self.modified = False
        super().__init__(on_update=on_update)
        dict.update(self, *args, **kwargs)

    def copy(self):
        missing = object()
        result = object.__new__(self.__class__)
        for name in self.__slots__:
            val = getattr(self, name, missing)
            if val is not missing:
                setattr(result, name, val)
        return result

    def __copy__(self):
        return self.copy()


class Session(ModificationTrackingDict):

    __slots__ = (*ModificationTrackingDict.__slots__, "sid", "new")

    def __init__(self, data, sid, new=False):
        super().__init__(data)
        self.sid = sid
        self.new = new

    def __repr__(self):
        return f"<{self.__class__.__name__} {dict.__repr__(self)}{'*' if self.should_save else ''}>"

    @property
    def should_save(self):
        return self.modified


class SessionStore:

    def __init__(self, session_class=None):
        if session_class is None:
            session_class = Session
        self.session_class = session_class

    def is_valid_key(self, key):
        return _sha1_re.match(key) is not None

    def generate_key(self, salt=None):
        return generate_key(salt)

    def new(self):
        return self.session_class({}, self.generate_key(), True)

    def save(self, session):
        pass

    def keep_alive(self, session):
        self.save(session)

    def delete(self, session):
        pass

    def get(self, sid):
        return self.session_class({}, sid, True)


_fs_transaction_suffix = ".__wz_sess"


class FilesystemSessionStore(SessionStore):

    def __init__(
        self,
        path=None,
        filename_template="werkzeug_%s.sess",
        session_class=None,
        renew_missing=False,
        mode=0o644,
    ):
        super().__init__(session_class)
        if path is None:
            path = tempfile.gettempdir()
        self.path = path
        assert not filename_template.endswith(_fs_transaction_suffix), (
            f"filename templates may not end with {_fs_transaction_suffix}"
        )
        self.filename_template = filename_template
        self.renew_missing = renew_missing
        self.mode = mode

    def get_session_filename(self, sid):
        return path.join(self.path, self.filename_template % sid)

    def save(self, session):
        fn = self.get_session_filename(session.sid)
        fd, tmp = tempfile.mkstemp(suffix=_fs_transaction_suffix, dir=self.path)
        try:
            os.fchmod(fd, self.mode)
            with os.fdopen(fd, "wb") as f:
                f.write(_json_dumps(dict(session)))
                f.flush()
                os.fsync(f.fileno())
            pathlib.Path(tmp).replace(fn)
        except OSError:
            _logger.warning(
                "Failed to persist session %r to %r", session.sid, fn, exc_info=True
            )
            try:
                pathlib.Path(tmp).unlink()
            except OSError:
                pass
            raise

    def delete(self, session):
        fn = self.get_session_filename(session.sid)
        try:
            pathlib.Path(fn).unlink()
        except OSError:
            pass

    def get(self, sid):
        if not self.is_valid_key(sid):
            return self.new()
        fn = pathlib.Path(self.get_session_filename(sid))
        try:
            with fn.open("rb") as f:
                data = _json_loads(f.read())
            if not isinstance(data, dict):
                raise TypeError(f"session payload is {type(data).__name__}, not dict")
        except OSError:
            _logger.debug(
                "Could not load session from disk. Use empty session.",
                exc_info=True,
            )
            if self.renew_missing:
                return self.new()
            data = {}
        except Exception:
            _logger.warning(
                "Corrupt session file %r; discarding it.", str(fn), exc_info=True
            )
            try:
                fn.unlink()
            except OSError:
                pass
            if self.renew_missing:
                return self.new()
            data = {}
        return self.session_class(data, sid, False)
