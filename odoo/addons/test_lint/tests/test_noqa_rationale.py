"""Lint test: every ``# noqa`` should carry a rationale.

First-iteration policy: scan all core Python files, log every violation,
**but do not fail the suite**.  This gives the team visibility on existing
debt without breaking CI on day one.

Once the legacy debt is cleaned up, flip ``ENFORCE`` to ``True`` (or wire
in a baseline/ratchet so only NEW violations fail) — see the comment at
the bottom of ``test_noqa_rationale``.
"""

import logging
from pathlib import Path

from odoo import tools

from . import _checker_noqa_rationale, lint_case

_logger = logging.getLogger(__name__)

# Flip to True once the legacy backlog is cleared.  Until then the test is
# advisory: it logs every violation as a warning so they show up in CI,
# but it does not fail the suite.
ENFORCE = False

# Skip patterns — files where bare ``# noqa`` is intentional fixture data.
_SKIP_FRAGMENTS = (
    "/test_lint/tests/_checker_noqa_rationale.py",  # the regex itself mentions noqa
    "/test_lint/tests/test_noqa_rationale.py",      # this file
)


def _is_core_path(path: str) -> bool:
    """True if *path* is under the core Odoo directory tree.

    Mirrors ``test_checkers._is_core_path`` so this lint is scoped to the
    code we own, not the surrounding addons workspace (enterprise,
    design-themes, customer addons).
    """
    root = tools.config.root_path  # .../core/odoo
    core_dir = str(Path(root).parent)  # .../core
    return path.startswith(core_dir)


class TestNoqaRationale(lint_case.LintCase):
    """Each ``# noqa`` suppression should explain *why* the rule was waived."""

    def test_noqa_rationale(self):
        violations: list[tuple[str, _checker_noqa_rationale.Violation]] = []

        for path in self.iter_module_files("*.py"):
            if not _is_core_path(path):
                continue
            if any(frag in path for frag in _SKIP_FRAGMENTS):
                continue
            try:
                source = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for v in _checker_noqa_rationale.find_violations(source):
                violations.append((path, v))

        if not violations:
            _logger.info("noqa rationale check: no violations across core")
            return

        # Group by file for readable log output.
        by_file: dict[str, list[_checker_noqa_rationale.Violation]] = {}
        for path, v in violations:
            by_file.setdefault(path, []).append(v)

        report_lines = [
            f"Found {len(violations)} ``# noqa`` suppression(s) "
            f"without rationale across {len(by_file)} file(s):"
        ]
        for path in sorted(by_file):
            report_lines.append(f"  {path}")
            for v in by_file[path]:
                report_lines.append(f"    - {v}")
        report = "\n".join(report_lines)

        if ENFORCE:
            self.fail(report)
        else:
            _logger.warning(
                "noqa rationale check (advisory; ENFORCE=False)\n%s", report,
            )

        # When the legacy backlog reaches zero, flip ``ENFORCE`` to ``True``
        # above — or replace the boolean with a baseline-ratchet that fails
        # only when the violation count INCREASES from a stored snapshot.
