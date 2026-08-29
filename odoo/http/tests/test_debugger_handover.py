from unittest import mock

from odoo.http import application


def test_no_handover_without_an_attached_debugger():
    """``gunicorn odoo.http:root`` reaches the application directly.

    setup/odoo-wsgi.example.py documents exactly that, and such a process can
    carry --dev=werkzeug in its environment with no DebuggedApplication
    anywhere. Deciding from the config rather than from what was actually
    wrapped would hand it an unhandled exception and a bare 500, in exchange
    for a traceback page nothing is there to render.
    """
    assert application.debugger_attached is False, (
        "importing odoo.http must not attach a debugger"
    )
    assert application._hands_over_to_the_debugger(None) is False


def test_handover_once_a_debugger_is_attached():
    with mock.patch.object(application, "debugger_attached", True):
        assert application._hands_over_to_the_debugger(None) is True


def test_a_serialising_dispatcher_is_exempt():
    req = mock.Mock()
    req.dispatcher.serializes_errors_in_dev_mode = True
    with mock.patch.object(application, "debugger_attached", True):
        assert application._hands_over_to_the_debugger(req) is False
    req.dispatcher.serializes_errors_in_dev_mode = False
    with mock.patch.object(application, "debugger_attached", True):
        assert application._hands_over_to_the_debugger(req) is True
