import re
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged

from ..controllers.observability import _JS_ERROR_KINDS, _JS_ERROR_PHASES


@tagged("post_install", "-at_install")
class TestJsErrorTaxonomy(TransactionCase):
    """The js_error beacon emitters and the server whitelist must agree.

    ``/web/observability/js_error`` coerces any ``kind`` / ``phase`` it does not
    recognise to ``"error"`` / ``"unknown"``. That is exactly how an
    ``asset_load_error`` (an auto-reloaded bundle failure) and a
    ``boot_mount_failed`` (a blank-page boot failure) were being logged as plain
    errors -- the two most operationally interesting events, unlabelled. Scan
    the files that build a beacon payload directly and assert every kind and
    phase they emit is in the server's taxonomy, so a new one fails here instead
    of degrading silently in production.
    """

    def test_emitted_kinds_and_phases_are_whitelisted(self):
        src = Path(__file__).resolve().parents[1] / "static" / "src"
        emitters = [
            src / "module_loader.js",
            src / "core" / "errors" / "error_beacon.js",
            src / "core" / "errors" / "boot_failure_overlay.js",
        ]
        kinds, phases = set(), set()
        for path in emitters:
            text = path.read_text(encoding="utf-8")
            kinds.update(re.findall(r'kind:\s*"([a-z_]+)"', text))
            for expr in re.findall(r"phase:\s*([^\n]*)", text):
                phases.update(re.findall(r'"([a-z_]+)"', expr))

        # Vacuity guard: a scan that matched nothing must fail, not pass.
        self.assertTrue(kinds, "no kind emitters found -- the scan reached nothing")
        self.assertTrue(phases, "no phase emitters found -- the scan reached nothing")

        self.assertLessEqual(
            kinds,
            _JS_ERROR_KINDS,
            f"js_error kind(s) emitted by the client but not whitelisted on the "
            f"server: {sorted(kinds - _JS_ERROR_KINDS)}",
        )
        self.assertLessEqual(
            phases,
            _JS_ERROR_PHASES,
            f"js_error phase(s) emitted by the client but not whitelisted on the "
            f"server: {sorted(phases - _JS_ERROR_PHASES)}",
        )
