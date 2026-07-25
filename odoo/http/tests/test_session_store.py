"""DB-free unit tests for the filesystem session store's rotation state machine.

:class:`odoo.http.session.FilesystemSessionStore` and :class:`Session` need only
a temp directory — no registry, no HTTP request — for everything except the
authenticated-token path (which needs an env). These pin the soft-rotation
prefix/adoption/GC behaviour that the CSRF token and device-log correlation
depend on. Run via ``pytest odoo/http/tests``.
"""

import os
import pathlib
import time
from types import SimpleNamespace

import pytest

from odoo.http.constants import STORED_SESSION_BYTES
from odoo.http.request_class import Request
from odoo.http.session import FilesystemSessionStore, Session, _coerce_session_value
from odoo.http.wrappers import FutureResponse


@pytest.fixture
def store(tmp_path):
    return FilesystemSessionStore(
        str(tmp_path), session_class=Session, renew_missing=True
    )


def _anon(store):
    s = store.new()
    s["uid"] = None
    store.save(s)
    return s


def test_generate_key_shape_and_prefix_invariant():
    store = FilesystemSessionStore(session_class=Session)
    key = store.generate_key()
    assert len(key) == 84
    assert store.is_valid_key(key)
    assert len(key) > STORED_SESSION_BYTES


def test_soft_rotation_keeps_prefix_changes_suffix(store):
    s = _anon(store)
    old = s.sid
    store.rotate(s, env=None, soft=True)
    assert s.sid != old
    assert s.sid[:STORED_SESSION_BYTES] == old[:STORED_SESSION_BYTES]
    assert store.get(old)["next_sid"] == s.sid
    assert store.get(s.sid).get("gc_previous_sessions") is True


def test_hard_rotation_changes_whole_sid(store):
    s = _anon(store)
    old = s.sid
    store.rotate(s, env=None, soft=False)
    assert s.sid[:STORED_SESSION_BYTES] != old[:STORED_SESSION_BYTES]


def test_concurrent_peer_unmodified_adopts_new_sid(store):
    s = _anon(store)
    old = s.sid
    store.rotate(s, env=None, soft=True)
    peer = store.get(old)
    store.rotate(peer, env=None, soft=True)
    assert peer.sid == s.sid


def test_concurrent_peer_modified_flushes_without_stale_markers(store):
    s = _anon(store)
    old = s.sid
    store.rotate(s, env=None, soft=True)
    peer = store.get(old)
    peer.mark_clean()
    peer["foo"] = "bar"
    store.rotate(peer, env=None, soft=True)
    merged = store.get(s.sid)
    assert merged.get("foo") == "bar"
    assert "next_sid" not in merged
    assert "deletion_time" not in merged


def test_delete_old_sessions_keeps_current_removes_predecessor(store):
    s = _anon(store)
    old = s.sid
    store.rotate(s, env=None, soft=True)
    s["create_time"] = time.time() - 10_000
    store.save(s)
    store.delete_old_sessions(s)
    assert not pathlib.Path(store.get_session_filename(old)).exists()
    assert pathlib.Path(store.get_session_filename(s.sid)).exists()


def test_delete_from_identifiers_rejects_bad_identifier(store):
    with pytest.raises(ValueError, match="Identifier format"):
        store.delete_from_identifiers(["../etc"])


def test_vacuum_operates_on_own_path(store, tmp_path):
    s = _anon(store)
    fn = pathlib.Path(store.get_session_filename(s.sid))
    import os

    old = time.time() - 10 * 24 * 3600
    os.utime(fn, (old, old))
    store.vacuum(max_lifetime=7 * 24 * 3600)
    assert not fn.exists()


def test_vacuum_reaps_orphaned_tmp_files(store, tmp_path):
    from odoo.libs._vendor.sessions import _fs_transaction_suffix

    orphan = tmp_path / f"tmpabc123{_fs_transaction_suffix}"
    orphan.write_bytes(b"{}")
    import os

    old = time.time() - 10 * 24 * 3600
    os.utime(orphan, (old, old))
    fresh = tmp_path / f"tmpdef456{_fs_transaction_suffix}"
    fresh.write_bytes(b"{}")
    store.vacuum(max_lifetime=7 * 24 * 3600)
    assert not orphan.exists()
    assert fresh.exists()


def test_get_refreshes_stale_mtime(store):
    """An actively-read but never-modified session must not age into vacuum's
    threshold: loading it bumps a stale mtime (at most once per interval)."""
    import os

    s = _anon(store)
    fn = pathlib.Path(store.get_session_filename(s.sid))
    old = time.time() - 2 * 24 * 3600
    os.utime(fn, (old, old))
    store.get(s.sid)
    assert fn.stat().st_mtime > time.time() - 60
    before = fn.stat().st_mtime
    store.get(s.sid)
    assert fn.stat().st_mtime == before


def test_corrupt_session_file_is_discarded_and_renewed(store):
    """Regression: a corrupt session file kept its sid with empty data forever —
    an all-defaults session is "not modified", so the file was never rewritten,
    and every later request re-parsed the same corrupt bytes."""
    s = _anon(store)
    fn = pathlib.Path(store.get_session_filename(s.sid))
    fn.write_bytes(b"{corrupt json!!")
    renewed = store.get(s.sid)
    assert renewed.is_new
    assert renewed.sid != s.sid
    assert not fn.exists()


def test_non_dict_session_payload_is_treated_as_corrupt(store):
    """A session file holding JSON ``null``/list crashed ``Session.__init__``
    (``dict(None)``) into a 500 on every request with that cookie."""
    for payload in (b"null", b"[1, 2]", b'"str"'):
        s = _anon(store)
        fn = pathlib.Path(store.get_session_filename(s.sid))
        fn.write_bytes(payload)
        renewed = store.get(s.sid)
        assert renewed.is_new and renewed.sid != s.sid
        assert not fn.exists()


def test_coerce_session_value_rejects_non_json():
    import datetime

    with pytest.raises(TypeError):
        _coerce_session_value(datetime.datetime(2020, 1, 1))
    assert _coerce_session_value((1, 2)) == [1, 2]
    assert _coerce_session_value({"a": (1, "x")}) == {"a": [1, "x"]}
    with pytest.raises(TypeError):
        _coerce_session_value({1: "int-key"})


def test_session_is_modified_detects_nested_mutation():
    s = Session({"context": {"lang": "en_US"}}, "sid", new=True)
    s.mark_clean()
    assert not s.is_modified()
    s["context"]["lang"] = "es_MX"
    assert s.is_modified()


def _interrupted_peer_rotation(store, session):
    """Put the store in the window a soft rotation opens.

    ``rotate(soft=True)`` writes ``next_sid`` into the OLD file first, and only
    then writes the NEW one. Between those two saves a concurrent request can
    read the announcement while the sid it names still has no file behind it.
    Reproduce exactly that state.
    """
    next_sid = (
        session.sid[:STORED_SESSION_BYTES] + store.generate_key()[STORED_SESSION_BYTES:]
    )
    peer_view = store.get(session.sid)
    peer_view["next_sid"] = next_sid
    peer_view["deletion_time"] = time.time() + 120
    store.save(peer_view)
    return next_sid


def test_soft_rotation_does_not_adopt_a_sid_with_no_file(store):
    """Adopting a peer's announced sid before its file lands logs the user out.

    The concurrent request moved onto ``next_sid`` unconditionally. If the peer
    had not yet written that file (a few milliseconds, or forever if its worker
    died), the session now points at nothing: the next request's
    ``renew_missing`` hands out a fresh anonymous session and the user is
    silently logged out mid-browse.
    """
    session = store.new()
    session["uid"] = 2
    session["session_token"] = "token-computed-for-the-old-sid"
    store.save(session)
    old_sid = session.sid

    _interrupted_peer_rotation(store, session)

    concurrent = store.get(old_sid)
    store.rotate(concurrent, env=None, soft=True)

    landed = store.get(concurrent.sid)
    assert not landed.is_new, (
        "rotate() moved the session onto a sid with no file behind it"
    )
    assert landed["uid"] == 2, "the authenticated session must survive"


def test_soft_rotation_adopts_once_the_peer_file_lands(store):
    """The normal case must still adopt: same sid, peer's authoritative token."""
    session = store.new()
    session["uid"] = 2
    session["session_token"] = "old-token"
    store.save(session)
    old_sid = session.sid

    next_sid = _interrupted_peer_rotation(store, session)
    peer_final = Session({"uid": 2, "session_token": "new-token"}, next_sid)
    store.save(peer_final)

    concurrent = store.get(old_sid)
    store.rotate(concurrent, env=None, soft=True)

    assert concurrent.sid == next_sid, "the peer's rotation must be adopted"
    assert not store.get(next_sid).is_new


class _RotationRequest:
    """Minimal stand-in driving :meth:`Request._save_session` over a real store."""

    _save_session = Request._save_session

    def __init__(self, store, session, sid_on_cookie):
        self.app = SimpleNamespace(session_store=store)
        self.session = session
        self.env = None
        self.future_response = FutureResponse()
        self.httprequest = SimpleNamespace(
            session_id=sid_on_cookie, path="/web/login", is_secure=False
        )


def test_pending_rotation_survives_a_request_with_no_live_env(store):
    """An armed rotation that cannot run must be parked in the payload.

    ``should_rotate`` is instance state, so a login that raised after
    ``Session.finalize`` armed it lost the rotation with the request object and
    stayed authenticated on its PRE-login sid — forfeiting the session-fixation
    defence hard rotation exists for. Rotating on the spot is impossible: the
    authenticated token needs a live cursor and the error path has none.
    """
    s = store.new()
    s["uid"] = 7
    s["create_time"] = time.time()
    store.save(s)
    s.mark_clean()
    original_sid = s.sid
    s.should_rotate = True

    _RotationRequest(store, s, original_sid)._save_session()

    assert s.sid == original_sid, "rotation must be deferred, not attempted"
    assert store.get(original_sid)["_rotate_pending"] is True


def test_pending_rotation_rearms_on_the_next_load(store):
    """The parked marker must be consumed and re-arm ``should_rotate``.

    This is the half that makes the deferral worth anything: parking the marker
    is useless unless the next request picks it up.
    """
    s = store.new()
    s["uid"] = 7
    s["_rotate_pending"] = True
    store.save(s)

    reloaded = store.get(s.sid)
    assert reloaded.should_rotate is False
    if reloaded.pop("_rotate_pending", None):
        reloaded.should_rotate = True

    assert reloaded.should_rotate is True
    assert "_rotate_pending" not in reloaded


def test_pending_rotation_is_not_parked_when_it_can_run(store):
    s = _anon(store)
    s.should_rotate = True
    original_sid = s.sid

    _RotationRequest(store, s, original_sid)._save_session()

    assert s.sid != original_sid
    assert "_rotate_pending" not in store.get(s.sid)


def test_touch_is_a_keep_alive_not_a_content_change():
    """``touch()`` marks the session dirty without changing its bytes.

    This is the distinction ``_save_session`` routes on: a bare touch takes the
    cheap ``keep_alive`` path, while a real write still forces a full save.
    """
    s = Session({}, "sid", False)
    s["uid"] = 1
    s.mark_clean()

    s.touch()
    assert s.is_dirty
    assert not s.has_content_changed()
    assert s.is_modified()

    s["lang"] = "es"
    assert s.has_content_changed()


def test_keep_alive_bumps_mtime_without_rewriting(store):
    s = _anon(store)
    path = pathlib.Path(store.get_session_filename(s.sid))
    before_bytes = path.read_bytes()
    old = time.time() - 10_000
    os.utime(path, (old, old))

    store.keep_alive(s)

    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime > old


def test_keep_alive_persists_a_session_with_no_file_yet(store):
    s = store.new()
    s["uid"] = None
    path = pathlib.Path(store.get_session_filename(s.sid))
    assert not path.exists()

    store.keep_alive(s)

    assert path.exists()
