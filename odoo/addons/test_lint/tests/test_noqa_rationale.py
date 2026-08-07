import logging
from pathlib import Path

from odoo import tools

from . import _checker_noqa_rationale, lint_case

_logger = logging.getLogger(__name__)

ENFORCE = False

_SKIP_FRAGMENTS = (
    "/test_lint/tests/_checker_noqa_rationale.py",
    "/test_lint/tests/test_noqa_rationale.py",
)


def _is_core_path(path: str) -> bool:
    root = tools.config.root_path
    core_dir = str(Path(root).parent)
    return path.startswith(core_dir)


class TestNoqaRationale(lint_case.LintCase):
    def test_noqa_rationale(self):
        violations: list[tuple[str, _checker_noqa_rationale.Violation]] = []

        for path in self.iter_module_files("*.py"):
            if not _is_core_path(path):
                continue
            if any(frag in path for frag in _SKIP_FRAGMENTS):
                continue
            try:
                source = Path(path).read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            violations.extend(
                (path, v) for v in _checker_noqa_rationale.find_violations(source)
            )

        if not violations:
            _logger.info("noqa rationale check: no violations across core")
            return

        by_file: dict[str, list[_checker_noqa_rationale.Violation]] = {}
        for path, v in violations:
            by_file.setdefault(path, []).append(v)

        report_lines = [
            (
                f"Found {len(violations)} ``# noqa`` suppression(s) "
                f"without rationale across {len(by_file)} file(s):"
            )
        ]
        for path in sorted(by_file):
            report_lines.append(f"  {path}")
            report_lines.extend(f"    - {v}" for v in by_file[path])
        report = "\n".join(report_lines)

        if ENFORCE:
            self.fail(report)
        else:
            _logger.warning(
                "noqa rationale check (advisory; ENFORCE=False)\n%s",
                report,
            )
