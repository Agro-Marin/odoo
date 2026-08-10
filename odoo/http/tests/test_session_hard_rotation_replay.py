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
    sess["uid"] = None
    sess["login"] = login
    store.save(sess)
    return sess


def test_soft_rotation_keeps_the_old_sid_resolvable():
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
    sess = _saved_session(store, "alice")
    cookie_sid = sess.sid

    store.rotate(sess, env=None, soft=False)

    assert sess.sid != cookie_sid
    assert store.get(cookie_sid).is_new, "the old sid no longer resolves"
    assert store.get(sess.sid).get("login") == "alice", "the new sid does"


def test_refresh_after_rotation_keys_on_the_current_sid(store):
    from odoo.http._retry import RequestRetryParticipant

    sess = _saved_session(store, "alice")
    cookie_sid = sess.sid
    store.rotate(sess, env=None, soft=False)

    class _FakeRequest:
        def __init__(self):
            self.session = sess

        def _get_session_and_dbname(self, sid=None):
            key = sid if sid is not None else cookie_sid
            return store.get(key), None

    request = _FakeRequest()
    RequestRetryParticipant(request).on_rollback(Exception("rolled back"))

    assert not request.session.is_new, "the refresh minted an anonymous session"
    assert request.session.get("login") == "alice", "the session was lost"


def test_save_reraises_on_persistence_failure(store, monkeypatch):
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
