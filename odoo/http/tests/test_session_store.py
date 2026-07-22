"""DB-free unit tests for the filesystem session store's rotation state machine.

:class:`odoo.http.session.FilesystemSessionStore` and :class:`Session` need only
a temp directory — no registry, no HTTP request — for everything except the
authenticated-token path (which needs an env). These pin the soft-rotation
prefix/adoption/GC behaviour that the CSRF token and device-log correlation
depend on. Run via ``pytest odoo/http/tests``.
"""

import pathlib
import time

import pytest

from odoo.http.constants import STORED_SESSION_BYTES
from odoo.http.session import FilesystemSessionStore, Session, _coerce_session_value


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
    # the stored prefix must be a strict prefix, else soft rotation can't work.
    assert len(key) > STORED_SESSION_BYTES


def test_soft_rotation_keeps_prefix_changes_suffix(store):
    s = _anon(store)
    old = s.sid
    store.rotate(s, env=None, soft=True)
    assert s.sid != old
    assert s.sid[:STORED_SESSION_BYTES] == old[:STORED_SESSION_BYTES]
    # the pre-rotation file points forward to the new sid.
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
    # a second request still holding the old cookie, no local edits.
    peer = store.get(old)
    store.rotate(peer, env=None, soft=True)
    assert peer.sid == s.sid  # adopted, not a divergent third sid


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
    s["create_time"] = time.time() - 10_000  # past the deletion timer
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
    assert not orphan.exists()  # crash orphan past the threshold: reaped
    assert fresh.exists()  # an in-flight save's tmp file is left alone


def test_get_refreshes_stale_mtime(store):
    """An actively-read but never-modified session must not age into vacuum's
    threshold: loading it bumps a stale mtime (at most once per interval)."""
    import os

    s = _anon(store)
    fn = pathlib.Path(store.get_session_filename(s.sid))
    old = time.time() - 2 * 24 * 3600
    os.utime(fn, (old, old))
    store.get(s.sid)
    assert fn.stat().st_mtime > time.time() - 60  # bumped to ~now
    # A fresh mtime is left untouched (no write amplification).
    before = fn.stat().st_mtime
    store.get(s.sid)
    assert fn.stat().st_mtime == before


def test_coerce_session_value_rejects_non_json():
    import datetime

    with pytest.raises(TypeError):
        _coerce_session_value(datetime.datetime(2020, 1, 1))
    # tuple coerces to list; nested dicts validated.
    assert _coerce_session_value((1, 2)) == [1, 2]
    assert _coerce_session_value({"a": (1, "x")}) == {"a": [1, "x"]}
    with pytest.raises(TypeError):
        _coerce_session_value({1: "int-key"})


def test_session_is_modified_detects_nested_mutation():
    s = Session({"context": {"lang": "en_US"}}, "sid", new=True)
    s.mark_clean()
    assert not s.is_modified()
    s["context"]["lang"] = "es_MX"  # in-place, bypasses __setitem__
    assert s.is_modified()
