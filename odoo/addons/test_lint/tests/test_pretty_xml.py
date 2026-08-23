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


# 3660 -> 3658: every XML file in the modules this fork authored is canonical.
# `base_account` 2, `project_hr` 2, `credential` 1, `test_base_order` 1 -- the
# set found by taking the offender list and keeping the modules whose manifest
# names AgroMarin as author. A module unit rather than a file count, the same
# shape as the `addons/mail` sweep below: the debt is paid per owner, so what
# the number bought can be stated.
#
# THE 3660 THIS REPLACES WAS ARITHMETIC, NOT A MEASUREMENT, AND NEVER
# REPRODUCED. It was predicted for a rebase composition as 3812 - 68 - 84 on the
# claim that the two parents canonicalised disjoint sets. Re-measured with the
# same code in detached worktrees, that claim is false:
#
#   876ba89f63b, the commit that banked 3660      3676
#   4d5b31750f5, HEAD before this change          3664
#   the same HEAD, six fork-authored files later  3658
#
# So the gate has been red on this test since the floor was written, by 16 and
# then by 4 as the tree converged on its own. The floor now says what the tree
# measures, and the six units are real debt paid rather than a number relaxed
# to meet the tree.
#
#   python odoo/addons/test_lint/tests/_pretty_xml.py --count odoo/addons addons
#
# 3811 -> 3744: `addons/mail` canonicalised, all 68 of its offenders.
# The tree held 3812 against the committed 3811 and had since before this
# branch -- a clean worktree of 3921edc2844 measures 3812 too -- so this
# gate was red for every commit in between.
UNFORMATTED_FLOOR = 3658
