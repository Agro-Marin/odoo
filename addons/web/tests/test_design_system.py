import re

import odoo.tests
from odoo.tools.sass_embedded import close_sass_compiler

GENERIC_FAMILIES = frozenset(
    {
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "ui-rounded",
        "math",
        "emoji",
        "fangsong",
    }
)

UNICODE_SUPPORT_FONT = '"Odoo Unicode Support Noto"'

FONT_DECLARATION_RE = re.compile(
    r"(--)?[\w-]*font[\w-]*\s*:\s*([^;{}]+)", re.IGNORECASE
)


@odoo.tests.tagged("-at_install", "post_install", "web_assets")
class TestDesignSystem(odoo.tests.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(close_sass_compiler)
        cls.css = {}
        cls.errors = {}
        for name in ("web.assets_backend", "web.assets_frontend"):
            bundle = cls.env["ir.qweb"]._get_asset_bundle(name, css=True, js=False)
            cls.css[name] = bundle.preprocess_css()
            cls.errors[name] = list(bundle.css_errors)

    def _complete_stacks(self, css):
        for match in FONT_DECLARATION_RE.finditer(css):
            value = match.group(2).strip()
            families = [f.strip() for f in value.split(",")]
            if len(families) > 1 and GENERIC_FAMILIES.intersection(
                f.lower() for f in families
            ):
                yield value

    def test_complete_font_stacks_carry_the_unicode_fallback(self):
        for bundle, css in self.css.items():
            stacks = set(self._complete_stacks(css))
            self.assertTrue(
                stacks,
                f"{bundle}: found no font stacks to check "
                f"(css={len(css)} bytes, errors={self.errors.get(bundle)})",
            )
            for stack in stacks:
                self.assertIn(
                    UNICODE_SUPPORT_FONT,
                    stack,
                    f"{bundle}: font stack ships without the Unicode fallback, so "
                    f"non-Latin text falls through to the platform default:\n  {stack}",
                )

    def test_font_stacks_list_no_family_twice(self):
        for bundle, css in self.css.items():
            for stack in set(self._complete_stacks(css)):
                families = [f.strip().lower() for f in stack.split(",")]
                duplicates = {f for f in families if families.count(f) > 1}
                self.assertFalse(
                    duplicates,
                    f"{bundle}: {sorted(duplicates)} listed more than once; every "
                    f"entry between the copies is unreachable:\n  {stack}",
                )

    def test_no_family_listed_after_the_generic_it_ends_with(self):
        allowed_after_generic = re.compile(r"emoji|symbol", re.IGNORECASE)
        for bundle, css in self.css.items():
            for stack in set(self._complete_stacks(css)):
                families = [f.strip() for f in stack.split(",")]
                first_generic = next(
                    i for i, f in enumerate(families) if f.lower() in GENERIC_FAMILIES
                )
                for family in families[first_generic + 1 :]:
                    self.assertRegex(
                        family,
                        allowed_after_generic,
                        f"{bundle}: {family!r} sits behind a generic family and can "
                        f"never be selected:\n  {stack}",
                    )
