import logging
import re

from odoo.libs.lint import scan_regex_patterns
from odoo.modules import get_resource_from_path

from . import lint_case

_logger = logging.getLogger(__name__)

TSTRING_PAT = r"(?s)_t\(\s*`.*?\s*`\s*\)"
UNDERSCORE_PAT = r"""\b_\(\s*['"]"""
PATTERNS = (TSTRING_PAT, UNDERSCORE_PAT)

TSTRING_RE = re.compile(TSTRING_PAT)
UNDERSCORE_RE = re.compile(UNDERSCORE_PAT)
EXPRESSION_RE = re.compile(r"\$\{.+?\}")


class TestJsTranslations(lint_case.LintCase):
    def check_text(self, text):
        error_list = []
        for m in TSTRING_RE.finditer(text):
            template_string = m.group(0)
            if EXPRESSION_RE.search(template_string):
                line_nb = text[: m.start()].count("\n") + 1
                error_list.append((line_nb, template_string))

        for m in UNDERSCORE_RE.finditer(text):
            lineno = text[: m.start()].count("\n") + 1
            error_list.append((lineno, None))

        return error_list

    def test_regular_expression(self):
        bad_js = """
        const foo = {
            valid: _t(`not useful but valid template-string`),
            invalid: _t(`invalid template-string
            that spans multiple lines ${expression}`)
        };
        """
        error_list = self.check_text(bad_js)
        self.assertEqual(len(error_list), 1)
        [(line, template_string)] = error_list
        self.assertEqual(line, 4)
        self.assertIn("invalid template-string", template_string)
        self.assertNotIn("but valid template-string", template_string)

    def test_regular_expression_long(self):
        bad_js = """
        thing = _t(
            `foo ${this + is(a, very) - long == expression}`
        );
        """

        error_list = self.check_text(bad_js)
        self.assertEqual(len(error_list), 1)
        [(line, template_string)] = error_list
        self.assertEqual(line, 2)
        self.assertIn("foo ${this + is(a, very) - long == expression}", template_string)

    def test_matches_underscore(self):
        bad_js = """
        const thing1 = _('literal0');
        const thing0 = _([]);
        const thing2 = _("literal1");
        """
        self.assertEqual(self.check_text(bad_js), [(2, None), (4, None)])

    def test_js_translations(self):
        results = scan_regex_patterns(
            lint_case.core_module_roots(),
            [".js"],
            list(PATTERNS),
            ["node_modules", "__pycache__"],
        )

        offenders = []
        for path, line, pat_idx, matched_text in results:
            if path.endswith("/lodash.js"):
                continue
            if "/lib/" in path and path.endswith(".min.js"):
                continue

            if pat_idx == 0:
                if not EXPRESSION_RE.search(matched_text):
                    continue
                prefix = "translated template string"
                suffix = " ".join(matched_text.split())[:100]
            else:
                prefix = "underscore.js used as a translation function"
                suffix = "_t is the JS translation function"

            try:
                mod, relative_path = get_resource_from_path(path)
            except TypeError:
                mod, relative_path = "?", path
            offenders.append(f"{mod}/{relative_path}:{line}: {prefix}: {suffix}")

        self.assert_ratchet(
            offenders,
            "lint_js_translation_call",
            "invalid translation call(s) in JS",
            "Use _t with a plain string; a template string cannot be extracted.",
        )
