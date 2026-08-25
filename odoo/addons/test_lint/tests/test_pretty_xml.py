import logging

from . import _pretty_xml
from .lint_case import LintCase, core_data_files

_logger = logging.getLogger(__name__)


class PrettyXmlLinter(LintCase):
    def _files(self):
        return core_data_files()

    def test_xml_formatting(self):
        violations: list[str] = []
        checked = 0
        for path in self._files():
            checked += 1
            if _pretty_xml.format_xml_file(path, dry_run=True) is True:
                violations.append(f"  {path}")

        _logger.info("checked %s XML data files", checked)
        self.assertTrue(checked, "the scan reached no XML data files at all")
        self.assert_ratchet(
            violations,
            "lint_xml_unformatted",
            "XML data file(s) not in canonical format",
            "Format them, then set the floor to what the same code measures:\n"
            "    python odoo/addons/test_lint/tests/_pretty_xml.py "
            "odoo/addons addons\n"
            "    python odoo/addons/test_lint/tests/_pretty_xml.py --count "
            "odoo/addons addons",
        )
