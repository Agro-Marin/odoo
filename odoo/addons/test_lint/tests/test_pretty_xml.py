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
            "Format them, then set the floor to what the same code measures:\n"
            "    python odoo/addons/test_lint/tests/_pretty_xml.py "
            "odoo/addons addons\n"
            "    python odoo/addons/test_lint/tests/_pretty_xml.py --count "
            "odoo/addons addons",
        )


# 3744 -> 3660 on the rebase onto origin/19.0-marin. The two parents canonicalised
# disjoint sets of files, so the composition keeps both and the arithmetic closes
# exactly. Measured with the same code the gate runs, in detached worktrees:
#
#   merge-base                        3812
#   origin/19.0-marin (-68, mail)     3744   (its committed floor reproduces)
#   this branch, pre-rebase (-84)     3728
#   merged (both)                     3660
#
#   3812 - 68 - 84 = 3660, with no file counted twice: origin's 68 are all
#   `addons/mail`, which this branch did not touch, and this branch's 84 are
#   elsewhere.
#
#   python odoo/addons/test_lint/tests/_pretty_xml.py --count odoo/addons addons
#
# 3811 -> 3744: `addons/mail` canonicalised, all 68 of its offenders.
# The tree held 3812 against the committed 3811 and had since before this
# branch -- a clean worktree of 3921edc2844 measures 3812 too -- so this
# gate was red for every commit in between.
UNFORMATTED_FLOOR = 3660
