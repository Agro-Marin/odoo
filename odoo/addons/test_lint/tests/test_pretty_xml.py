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


# 3811 -> 3744: `addons/mail` canonicalised, all 68 of its offenders.
# The tree held 3812 against the committed 3811 and had since before this
# branch -- a clean worktree of 3921edc2844 measures 3812 too -- so this
# gate was red for every commit in between.
UNFORMATTED_FLOOR = 3744
