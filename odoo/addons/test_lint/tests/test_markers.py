import logging
from pathlib import Path

import odoo
from odoo.libs.lint import scan_byte_patterns

from . import lint_case

_logger = logging.getLogger(__name__)

MARKERS = [b"<" * 7, b">" * 7]
EXTENSIONS = [".py", ".js", ".xml", ".less", ".sass"]

NUL = [b"\x00"]
NUL_EXTENSIONS = [*EXTENSIONS, ".scss", ".css"]


def _scan_roots() -> list[str]:
    return sorted(
        {
            str(Path(p).resolve())
            for p in [*lint_case.core_module_roots(), *odoo.__path__]
            if lint_case.is_core_path(str(Path(p).resolve()))
        }
    )


class TestConflictMarkers(lint_case.LintCase):
    def test_conflict_markers(self):
        roots = _scan_roots()
        self.assertTrue(roots, "the scan reached no roots at all")

        results = scan_byte_patterns(
            roots,
            EXTENSIONS,
            MARKERS,
            ["node_modules", "__pycache__"],
        )

        self.assert_ratchet(
            sorted(f"{path}:{line}" for path, line, _ in results),
            "lint_conflict_marker",
            "conflict marker(s) left in the tree",
            "Finish the merge.",
        )
        _logger.info("conflict marker scan complete over %s root(s)", len(roots))


class TestNulBytes(lint_case.LintCase):
    def test_no_nul_bytes(self):
        roots = _scan_roots()
        self.assertTrue(roots, "the scan reached no roots at all")

        results = scan_byte_patterns(
            roots,
            NUL_EXTENSIONS,
            NUL,
            ["node_modules", "__pycache__"],
        )

        self.assert_ratchet(
            sorted(f"{path}:{line}" for path, line, _ in results),
            "lint_nul_byte",
            "source file line(s) holding a raw NUL byte, which makes git treat "
            "the whole file as binary and diff it as such",
            r"Write the escape \0 instead of the byte. It is the same string at "
            r"runtime and leaves the file textual.",
        )
        _logger.info("NUL byte scan complete over %s root(s)", len(roots))
