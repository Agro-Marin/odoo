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
            UNFORMATTED_FLOOR,
            "XML data file(s) not in canonical format",
            "Run `_pretty_xml.py` over this repository, then lower the floor.",
        )


# The debt this gate inherits. Run `_pretty_xml.py` over the repository to
# take it to 0 -- verified to preserve every file -- and lower this in the
# same change.
UNFORMATTED_FLOOR = 3827
