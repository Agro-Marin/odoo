import logging
import os
import pathlib

from odoo.libs.debug_log import DebugLog
from odoo.libs.json import dumps_bytes as _json_dumps
from odoo.libs.json import loads as _json_loads

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)


class SessionStore:

    def __init__(self, session_class):
        self.session_class = session_class

    def is_valid_key(self, key):
        raise NotImplementedError(
            f"{type(self).__name__} must define the session key format"
        )

    def generate_key(self, salt=None):
        raise NotImplementedError(
            f"{type(self).__name__} must define the session key format"
        )

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

    def __init__(self, path, session_class, renew_missing=False, mode=0o600):
        super().__init__(session_class)
        self.path = path
        self.renew_missing = renew_missing
        self.mode = mode

    def get_session_filename(self, sid):
        raise NotImplementedError(
            f"{type(self).__name__} must define the on-disk session layout"
        )

    def delete(self, session):
        fn = self.get_session_filename(session.sid)
        try:
            pathlib.Path(fn).unlink()
        except OSError:
            _debug.lifecycle("session_store.deleted", existed=False)
            return
        _debug.lifecycle("session_store.deleted", existed=True)

    def get(self, sid):
        if not self.is_valid_key(sid):
            _debug.logic("session_store.get", outcome="invalid_key", renewed=True)
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
            _debug.logic(
                "session_store.get", outcome="missing", renewed=self.renew_missing
            )
            if self.renew_missing:
                return self.new()
            data = {}
        except Exception as exc:  # debuglog
            _logger.warning(
                "Corrupt session file %r; discarding it.", str(fn), exc_info=True
            )
            _debug.logic(
                "session_store.get",
                outcome="corrupt",
                error=type(exc).__name__,
                renewed=self.renew_missing,
            )
            try:
                fn.unlink()
            except OSError:
                pass
            if self.renew_missing:
                return self.new()
            data = {}
        else:
            _debug.logic("session_store.get", outcome="loaded", keys=len(data))
        return self.session_class(data, sid, False)
