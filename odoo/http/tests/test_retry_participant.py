"""``RequestRetryParticipant`` — restoring an HTTP request for a replay.

``retrying()`` may run a handler more than once. These assertions used to live
in ``tests/service/test_model.py``, driving the whole retry loop with
``odoo.http`` patched, because the transaction primitive did this work itself.
Since 2026-08-09 the transport supplies a participant
(``odoo.service.transaction.RetryParticipant``), so the behaviour can be
exercised where it lives, without a retry loop, a cursor or an environment.
"""

from unittest.mock import MagicMock

import pytest

from odoo.http._retry import RequestRetryParticipant, current_request_participant


def _request(**kwargs):
    request = MagicMock(**kwargs)
    request._get_session_and_dbname.return_value = (MagicMock(), "testdb")
    return request


class TestOnRollback:
    def test_the_session_is_refetched_by_its_sid(self):
        """Session mutations are transaction-coupled, so a rolled-back request
        must not keep the object it mutated."""
        request = _request()
        request.session.sid = "abc123"
        new_session = MagicMock()
        request._get_session_and_dbname.return_value = (new_session, "testdb")

        RequestRetryParticipant(request).on_rollback(Exception("boom"))

        request._get_session_and_dbname.assert_called_once_with(sid="abc123")
        assert request.session is new_session

    def test_a_request_with_no_sid_still_refetches(self):
        request = _request()
        del request.session.sid
        RequestRetryParticipant(request).on_rollback(Exception("boom"))
        request._get_session_and_dbname.assert_called_once_with(sid=None)


class TestOnRetry:
    def test_seekable_uploads_are_rewound(self):
        upload = MagicMock()
        upload.seekable.return_value = True
        request = _request()
        request.httprequest.files.items.return_value = [("photo", upload)]

        RequestRetryParticipant(request).on_retry(Exception("boom"))

        upload.seek.assert_called_once_with(0)

    def test_a_non_seekable_upload_raises_rather_than_replaying_a_partial_stream(self):
        upload = MagicMock()
        upload.seekable.return_value = False
        request = _request()
        request.httprequest.files.items.return_value = [("upload", upload)]

        with pytest.raises(
            RuntimeError, match="Cannot retry request on input file 'upload'"
        ):
            RequestRetryParticipant(request).on_retry(Exception("boom"))

    def test_the_replay_hook_is_invoked(self):
        """``_reset_for_replay`` is the same hook the RO->RW cursor upgrade
        uses, so the two replay paths cannot drift."""
        request = _request()
        request.httprequest.files.items.return_value = []
        RequestRetryParticipant(request).on_retry(Exception("boom"))
        request._reset_for_replay.assert_called_once_with()

    def test_a_request_without_the_replay_hook_does_not_crash(self):
        """``bus.websocket`` passes a request object with no
        ``_reset_for_replay``; the guard is ``if reset is not None``, and a
        MagicMock would auto-create the attribute and hide its absence --
        which is why this uses ``spec``."""
        request = MagicMock(spec=["_get_session_and_dbname", "httprequest", "session"])
        request.httprequest.files.items.return_value = []
        assert not hasattr(request, "_reset_for_replay")
        RequestRetryParticipant(request).on_retry(Exception("boom"))  # must not raise


class TestUncommittedWarningSuppression:
    def test_a_detached_database_suppresses_the_warning(self):
        request = _request(database_detached=True)
        assert RequestRetryParticipant(request).suppresses_uncommitted_warning()

    def test_an_ordinary_request_does_not(self):
        request = _request(database_detached=False)
        assert not RequestRetryParticipant(request).suppresses_uncommitted_warning()

    def test_a_stand_in_request_without_the_attribute_does_not(self):
        """Tests patch ``request`` and ``borrow_request`` swaps it; missing the
        warning on such a stand-in is a smaller failure than raising here."""
        request = MagicMock(spec=["_get_session_and_dbname", "httprequest", "session"])
        assert not RequestRetryParticipant(request).suppresses_uncommitted_warning()


class TestResolution:
    def test_off_request_there_is_no_participant(self):
        assert current_request_participant() is None
