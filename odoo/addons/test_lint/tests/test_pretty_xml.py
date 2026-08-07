import logging
from pathlib import Path

from . import _pretty_xml
from .lint_case import LintCase, core_xml_files

_logger = logging.getLogger(__name__)


class PrettyXmlLinter(LintCase):
    """Assert that XML data files conform to the canonical formatter output.

    Run the standalone formatter to resolve all violations at once::

        p314o19marin/bin/python odoo/odoo/addons/test_lint/tests/_pretty_xml.py odoo

    **Scoped to what the fixer will actually fix.** This test used to flag
    12 665 files while the fixer declined 9 876 of them -- everything under
    ``static/`` and everything in a sibling checkout -- so the remediation it
    printed could not make it pass, however many times it was run. Both sides
    now ask :func:`_pretty_xml.is_formattable`, and this one additionally scopes
    to the repository the fork owns: reformatting ``enterprise`` would only make
    the next upstream merge conflict.
    """

    def _files(self):
        for xml_file in core_xml_files():
            path = Path(xml_file)
            if _pretty_xml.is_formattable(path):
                yield path

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


#: Files still awaiting a formatting pass. Reformatting 3 827 files in one
#: change would collide with every other branch in flight, so the debt is frozen
#: and drained module by module instead.
#:
#: Re-measured 2026-08-07 after the formatter stopped rewriting the inside of
#: XML comments, which is why the number moved by one: canonical form itself
#: changed, so which files already match it did too. A count here is only ever
#: a reading of the *current* definition of canonical -- it is not comparable
#: across a change to the formatter, and pretending otherwise is how a floor
#: becomes folklore.
UNFORMATTED_FLOOR = 3827
