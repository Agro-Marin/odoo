import re

from odoo.libs.lint import scan_regex_patterns
from odoo.modules import get_resource_from_path

from . import lint_case

BS_RAMP_PAT = r"var\(\s*--gray-[1-9]00\s*[,)]"
BS_RAMP_RE = re.compile(BS_RAMP_PAT)

ALLOWED = {
    "website/static/src/builder/plugins/font/add_font_dialog.xml",
    "sign/static/src/css/green_saving_reports.scss",
}


class TestGreyRampToken(lint_case.LintCase):
    def check_text(self, text):
        return sorted(
            text[: m.start()].count("\n") + 1 for m in BS_RAMP_RE.finditer(text)
        )

    def test_regular_expression(self):
        bad = """
        a { color: var(--gray-100); }
        b { color: var(--o-gray-100); }
        c { color: var(--gray-400, #fff); }
        d { color: var(--gray-color); }
        """
        self.assertEqual(self.check_text(bad), [2, 4])

    def test_no_bootstrap_ramp_references(self):
        results = scan_regex_patterns(
            lint_case.core_module_roots(),
            [".scss", ".xml", ".css"],
            [BS_RAMP_PAT],
            ["node_modules", "__pycache__"],
        )

        offenders = []
        for path, line, _idx, matched in results:
            if "/static/lib/" in path or "/static/tests/" in path:
                continue
            try:
                mod, relative_path = get_resource_from_path(path)
            except TypeError:
                mod, relative_path = "?", path
            if f"{mod}/{relative_path}" in ALLOWED:
                continue
            offenders.append(f"{mod}/{relative_path}:{line}: {matched.strip()}")

        self.assert_ratchet(
            offenders,
            "lint_bootstrap_grey_ramp",
            "reference(s) to Bootstrap's grey ramp",
            "It is wired to this palette in the backend bundles only, so this "
            "renders differently on the frontend. Use `--o-gray-*`.",
        )
