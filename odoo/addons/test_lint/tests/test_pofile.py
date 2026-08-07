import logging
from collections import Counter

from odoo.modules import get_modules
from odoo.tools.misc import file_path
from odoo.tools.translate import translation_file_reader

from . import lint_case

_logger = logging.getLogger(__name__)


def _key(entry):
    match entry["type"]:
        case "model":
            return ("model", entry["name"], entry["imd_name"])
        case "model_terms":
            return ("model_terms", entry["name"], entry["imd_name"], entry["src"])
        case "code":
            return ("code", entry["src"])
    return None


class PotLinter(lint_case.LintCase):
    def test_pot_duplicate_entries(self):
        offenders = []
        checked = 0
        for module in get_modules():
            try:
                filename = file_path(f"{module}/i18n/{module}.pot")
            except FileNotFoundError:
                continue
            if not lint_case.is_core_path(filename):
                continue
            checked += 1
            counts = Counter(map(_key, translation_file_reader(filename)))
            offenders.extend(
                f"{module}: {count}x {key}"
                for key, count in counts.items()
                if count > 1
            )

        _logger.info("checked %s .pot file(s)", checked)
        self.assertTrue(checked, "the scan reached no .pot files at all")
        self.assert_ratchet(
            offenders,
            0,
            "duplicate entry/entries in a .pot file",
            "Regenerate the .pot, or drop the repeated term.",
        )
