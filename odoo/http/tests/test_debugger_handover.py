from unittest import mock

from odoo.http import application


def test_no_handover_without_an_attached_debugger():
    assert application.debugger_attached is False, (
        "importing odoo.http must not attach a debugger"
    )
    assert application._is_debugger_handover_required(None) is False


def test_handover_once_a_debugger_is_attached():
    with mock.patch.object(application, "debugger_attached", True):
        assert application._is_debugger_handover_required(None) is True


def test_a_serialising_dispatcher_is_exempt():
    req = mock.Mock()
    req.dispatcher.serializes_errors_in_dev_mode = True
    with mock.patch.object(application, "debugger_attached", True):
        assert application._is_debugger_handover_required(req) is False
    req.dispatcher.serializes_errors_in_dev_mode = False
    with mock.patch.object(application, "debugger_attached", True):
        assert application._is_debugger_handover_required(req) is True
