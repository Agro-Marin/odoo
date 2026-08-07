import logging
from pathlib import Path

from . import _pretty_xml
from .lint_case import LintCase

_logger = logging.getLogger(__name__)


class PrettyXmlLinter(LintCase):
    def test_xml_formatting(self):
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
