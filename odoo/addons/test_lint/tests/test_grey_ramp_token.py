import logging
import re

from odoo.libs.lint.scan import scan_regex_patterns
from odoo.modules import get_resource_from_path

from . import lint_case

_logger = logging.getLogger(__name__)

#: `var(--gray-100)` … `var(--gray-900)`, Bootstrap's ramp. One definition,
#: compiled for the self-test below and handed to the Rust scanner as text: a
#: self-test that validates a *copy* stops answering for the pattern the scan
#: actually runs the moment either is edited. Stating it once is only possible
#: because nothing here needs a flag — `test_jstranslate` keeps two spellings
#: because the Rust engine takes `(?s)` inline and Python takes `re.DOTALL`.
BS_RAMP_PAT = r"var\(\s*--gray-[1-9]00\s*[,)]"
BS_RAMP_RE = re.compile(BS_RAMP_PAT)

#: Uses that mean Bootstrap's ramp on purpose. Both predate the rule.
ALLOWED = {
    # A website builder dialog, rendered in the website's own Bootstrap
    # context, where Bootstrap's grey is the consistent choice.
    "website/static/src/builder/plugins/font/add_font_dialog.xml",
    # Its own bundle (`sign.assets_green_report`), which carries neither
    # `bootstrap_overridden.scss` nor `tokens.scss`; what this resolves to
    # there has not been traced, and changing it is not this rule's business.
    "sign/static/src/css/green_saving_reports.scss",
}


class TestGreyRampToken(lint_case.LintCase):
    """Component styling must reach the grey ramp through ``--o-gray-*``.

    Bootstrap's ``--gray-*`` is wired to this palette by
    ``bootstrap_overridden.scss``, which only the backend bundles carry. On the
    frontend Bootstrap keeps its own greys, so the same declaration is #e9ecef
    there and #e2e8f0 in the backend — and #ced4da against #94a3b8 at
    ``--gray-400``. A file that ships in both renders differently in each, and
    nothing says so at the point of use.

    ``--o-gray-*`` is published from ``$o-grays`` by ``tokens.scss``, which
    rides both, so it follows whatever palette the bundle actually compiled —
    including ``primary_variables_print.scss``, which restates the ramp for
    print on purpose.
    """

    def check_text(self, text):
        """Return the 1-based line numbers of Bootstrap-ramp references."""
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
            self._module_roots(),
            [".scss", ".xml", ".css"],
            [BS_RAMP_PAT],
            ["node_modules", "__pycache__"],
        )

        failures = 0
        for path, line, _idx, matched in results:
            if "/static/lib/" in path or "/static/tests/" in path:
                continue
            try:
                mod, relative_path, _ = get_resource_from_path(path)
            except TypeError:
                mod, relative_path = "?", path
            if f"{mod}/{relative_path}" in ALLOWED:
                continue

            failures += 1
            _logger.error(
                "Bootstrap's grey ramp referenced in `%s/%s` at line %s: %s. "
                "It is wired to this palette in the backend bundles only, so "
                "this renders differently on the frontend. Use `--o-gray-*`.",
                mod,
                relative_path,
                line,
                matched.strip(),
            )

        self.assertEqual(
            failures,
            0,
            "Use `--o-gray-*` for this palette's grey ramp; see the errors above.",
        )
