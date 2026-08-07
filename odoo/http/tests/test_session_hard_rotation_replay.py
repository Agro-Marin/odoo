"""A hard rotation must survive the request being replayed or failing.

``Request._save_session`` hard-rotates (``rotate(sess, env)``, i.e. ``soft=False``)
whenever ``should_rotate`` is set -- which ``Session.finalize()`` and
``Session.logout()`` do, so login, MFA finalisation and logout all take this
branch.  ``rotate(soft=False)`` calls ``self.delete(session)`` *before* the new
sid's file is written.

Meanwhile ``service/transaction.py::retrying`` calls ``_refresh_request_session``
on **every** failure path (retry *and* raise), and that re-reads the session via
``Request._get_session_and_dbname``, which keys off ``httprequest.session_id`` --
the sid in the client's *cookie*, not the rotated ``session.sid``.

Order of events inside ``retrying``: ``func()`` runs to completion (rotating and
persisting the session), and only then does ``env.cr.flush()`` issue the
handler's buffered writes.  So a login whose flush hits a serialization failure
-- e.g. a concurrent write to the same ``res.users`` row -- rotates first and
fails second, and the refresh then looks up a sid whose file has been unlinked.
With ``renew_missing=True`` the store answers with a brand-new anonymous
session, so a user who authenticated successfully is logged out.

Soft rotation is immune by construction: it parks ``next_sid`` in the old file
and keeps it alive for ``SESSION_DELETION_TIMER``.  These tests pin that
asymmetry, so the fix (write-then-delete, or reuse the soft grace window) can be
verified rather than argued.
"""

import pathlib

import pytest

from odoo.http.session import FilesystemSessionStore, Session


@pytest.fixture
def store(tmp_path):
    return FilesystemSessionStore(
        str(tmp_path), session_class=Session, renew_missing=True
    )


def _saved_session(store, login):
    sess = store.new()
    sess["uid"] = None  # rotate() only needs an env when uid is set
    sess["login"] = login
    store.save(sess)
    return sess


def test_soft_rotation_keeps_the_old_sid_resolvable():
    """Reference behaviour: the grace window a replay can follow."""
    import tempfile

    store = FilesystemSessionStore(
        tempfile.mkdtemp(), session_class=Session, renew_missing=True
    )
    sess = _saved_session(store, "bob")
    cookie_sid = sess.sid

    store.rotate(sess, env=None, soft=True)

    replayed = store.get(cookie_sid)
    assert not replayed.is_new
    assert replayed["next_sid"] == sess.sid


def test_hard_rotation_unlinks_the_cookie_sid(store):
    """The condition that makes the refresh key matter."""
    sess = _saved_session(store, "alice")
    cookie_sid = sess.sid

    # What login / MFA / logout do (Request._save_session -> rotate(sess, env)).
    store.rotate(sess, env=None, soft=False)

    assert sess.sid != cookie_sid
    assert store.get(cookie_sid).is_new, "the old sid no longer resolves"
    assert store.get(sess.sid).get("login") == "alice", "the new sid does"


def test_refresh_after_rotation_keys_on_the_current_sid(store):
    """``_refresh_request_session`` must follow the rotation, not the cookie.

    Stands in for the retrying() failure path without needing a WSGI stack:
    what matters is which sid the re-read is keyed on.
    """
    from odoo.service.transaction import _refresh_request_session

    sess = _saved_session(store, "alice")
    cookie_sid = sess.sid
    store.rotate(sess, env=None, soft=False)

    class _FakeRequest:
        """Only the surface _refresh_request_session touches."""

        def __init__(self):
            self.session = sess

        def _get_session_and_dbname(self, sid=None):
            # Mirrors Request._get_session_and_dbname's key selection.
            key = sid if sid is not None else cookie_sid
            return store.get(key), None

    request = _FakeRequest()
    _refresh_request_session(request)

    assert not request.session.is_new, "the refresh minted an anonymous session"
    assert request.session.get("login") == "alice", "the session was lost"


def test_save_reraises_on_persistence_failure(store, monkeypatch):
    """B4: the store must not swallow an OSError and return as if it saved.

    A swallowed failure let the caller rotate + set a cookie naming a sid with
    no file behind it — a silent logout under disk pressure.
    """
    sess = store.new()
    sess["uid"] = None
    monkeypatch.setattr(
        pathlib.Path,
        "replace",
        lambda self, target: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError):
        store.save(sess)


def test_hard_rotation_preserves_old_file_when_the_new_save_fails(store, monkeypatch):
    """B3: a failed save during hard rotation must leave the old session intact.

    Before the fix ``rotate`` deleted the old file *first*, so a save failure
    (or a crash) between the delete and the write destroyed the session
    outright. Now the new file is written before the old one is removed, so a
    failure leaves the old — still valid — session in place.
    """
    sess = _saved_session(store, "alice")
    cookie_sid = sess.sid
    old_file = store.get_session_filename(cookie_sid)
    assert pathlib.Path(old_file).exists()

    def boom(self, session):
        raise OSError("disk full")

    monkeypatch.setattr(type(store), "save", boom)
    with pytest.raises(OSError):
        store.rotate(sess, env=None, soft=False)
    monkeypatch.undo()

    assert pathlib.Path(old_file).exists(), (
        "the old session file must survive a failed rotation"
    )
    assert store.get(cookie_sid).get("login") == "alice", (
        "the old session still resolves"
    )
