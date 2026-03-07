"""Lint check: XML data files must use canonical 2-space formatting."""

import logging
from pathlib import Path

from . import _pretty_xml
from .lint_case import LintCase

_logger = logging.getLogger(__name__)


class PrettyXmlLinter(LintCase):
    """Assert that XML data files conform to the canonical formatter output.

    Run the standalone formatter to resolve all violations at once::

        ./venv/odoo/bin/python core/odoo/addons/test_lint/tests/_pretty_xml.py addons_custom core
    """

    def test_xml_formatting(self):
        """Assert that XML files are formatted with canonical 2-space indentation."""
        violations: list[str] = []
        for xml_file in self.iter_module_files("*.xml"):
            result = _pretty_xml.format_xml_file(Path(xml_file), dry_run=True)
            if result is True:
                violations.append(f"  {xml_file}")

        if violations:
            self.fail(
                "XML files need formatting (run _pretty_xml.py to fix):\n"
                + "\n".join(violations)
            )
