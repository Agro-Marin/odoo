import logging
from pathlib import Path

import odoo
from odoo.libs.lint import scan_byte_patterns

from . import lint_case

_logger = logging.getLogger(__name__)

MARKERS = [b"<" * 7, b">" * 7]
EXTENSIONS = [".py", ".js", ".xml", ".less", ".sass"]


class TestConflictMarkers(lint_case.LintCase):
    def test_conflict_markers(self):
        roots = sorted(
            {
                str(Path(p).resolve())
                for p in [*lint_case.core_module_roots(), *odoo.__path__]
                if lint_case.is_core_path(str(Path(p).resolve()))
            }
        )
        self.assertTrue(roots, "the scan reached no roots at all")

        results = scan_byte_patterns(
            roots,
            EXTENSIONS,
            MARKERS,
            ["node_modules", "__pycache__"],
        )

        self.assert_ratchet(
            sorted(f"{path}:{line}" for path, line, _ in results),
            0,
            "conflict marker(s) left in the tree",
            "Finish the merge.",
        )
        _logger.info("conflict marker scan complete over %s root(s)", len(roots))
