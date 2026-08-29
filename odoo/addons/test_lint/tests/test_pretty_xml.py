import logging

from . import _xml_sweep
from .lint_case import LintCase

_logger = logging.getLogger(__name__)


class PrettyXmlLinter(LintCase):
    def test_xml_formatting(self):
        sweep = _xml_sweep.formatter_sweep()
        _logger.info("checked %s XML data files", sweep.checked)
        self.assertTrue(sweep.checked, "the scan reached no XML data files at all")
        self.assert_ratchet(
            sweep.changed,
            "lint_xml_unformatted",
            "XML data file(s) not in canonical format",
            "Format them, then bank the new floor:\n"
            "    python odoo/addons/test_lint/tests/_pretty_xml.py odoo/addons addons",
        )

    def test_no_data_file_is_unparseable(self):
        sweep = _xml_sweep.formatter_sweep()
        self.assertFalse(
            sweep.unparseable,
            f"{len(sweep.unparseable)} file(s) selected as XML data do not parse. "
            f"Either they are fixtures that do not belong in the selection, or "
            f"they are broken:\n  " + "\n  ".join(sweep.unparseable),
        )
