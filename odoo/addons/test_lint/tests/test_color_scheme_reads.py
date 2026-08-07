import logging
import re

from odoo.libs.lint import scan_regex_patterns
from odoo.modules import get_resource_from_path

from . import lint_case

_logger = logging.getLogger(__name__)

COOKIE_GET_PAT = r"""cookie\.get\(\s*["']color_scheme["']\s*\)"""
COOKIE_SET_PAT = r"""cookie\.set\(\s*["']color_scheme["']"""
RAW_COOKIE_PAT = r"""document\.cookie[^;\n]*color_scheme"""
PATTERNS = (COOKIE_GET_PAT, COOKIE_SET_PAT, RAW_COOKIE_PAT)

REGEXES = tuple(re.compile(pattern) for pattern in PATTERNS)

ALLOWED_SUFFIXES = ("/web/static/src/core/color_scheme.js",)


class TestColorSchemeReads(lint_case.LintCase):
    def check_text(self, text):
        return sorted(
            text[: m.start()].count("\n") + 1
            for regex in REGEXES
            for m in regex.finditer(text)
        )

    def test_regular_expression(self):
        bad_js = """
        const a = cookie.get("color_scheme") === "dark";
        const b = cookie.get('color_scheme');
        const c = colorScheme.isDark;
        const d = document.cookie.includes("color_scheme=dark");
        const e = cookie.get("content_density");
        cookie.set("color_scheme", newScheme);
        cookie.set("content_density", density);
        """
        self.assertEqual(self.check_text(bad_js), [2, 3, 5, 7])

    def test_no_direct_cookie_reads(self):
        results = scan_regex_patterns(
            lint_case.core_module_roots(),
            [".js"],
            list(PATTERNS),
            ["node_modules", "__pycache__"],
        )

        offenders = []
        for path, line, _pat_idx, matched_text in results:
            if path.endswith(ALLOWED_SUFFIXES):
                continue
            if "/static/lib/" in path:
                continue
            if "/static/tests/" in path:
                continue

            try:
                mod, relative_path, _ = get_resource_from_path(path)
            except TypeError:
                mod, relative_path = "?", path
            offenders.append(f"{mod}/{relative_path}:{line}: {matched_text.strip()}")

        self.assert_ratchet(
            offenders,
            0,
            "direct use(s) of the color_scheme cookie",
            "Read it through `colorScheme` from @web/core/color_scheme "
            "(`colorScheme.isDark`, `colorScheme.current`); to change it, save "
            "the setting and have the page re-served.",
        )
