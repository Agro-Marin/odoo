"""Invariants over the *compiled* design system.

``test_assetsbundle`` covers the pipeline that delivers the CSS — ordering,
globs, invalidation, RTL, sourcemaps. Nothing covered the CSS it delivers, so a
design-token regression reached the browser silently: three of the four stacks
built by ``o-add-unicode-support-font()`` had quietly stopped carrying the
fallback that gives non-Latin scripts coverage, and every bundle still compiled.

These tests compile the real bundles once and assert properties of the output,
which is the only place such a regression is observable.
"""

import re

import odoo.tests
from odoo.tools.sass_embedded import close_sass_compiler

# A stack ending in a CSS generic family is a *complete* stack — the one kind
# that has to carry the fallback. Single-family declarations (`font-family:
# "Inter"` in an @font-face, `inherit`, `var(--x)`) are not stacks and are
# skipped.
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

# Stacks reach the browser both as `font-family:` and as the custom properties
# that back it (`--font-sans-serif`, `--headings-font-family`, …); the frontend
# bundle emits them almost entirely as the latter, so matching `font-family:`
# alone silently checked nothing there.
FONT_DECLARATION_RE = re.compile(
    r"(--)?[\w-]*font[\w-]*\s*:\s*([^;{}]+)", re.IGNORECASE
)


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
        """Yield every font declaration whose value contains a generic family.

        Containment, not "ends with": the stacks deliberately trail emoji fonts
        behind the generic, so keying on the last entry skipped every one of them
        and left the check asserting nothing.
        """
        for match in FONT_DECLARATION_RE.finditer(css):
            value = match.group(2).strip()
            families = [f.strip() for f in value.split(",")]
            if len(families) > 1 and GENERIC_FAMILIES.intersection(
                f.lower() for f in families
            ):
                yield value

    def test_complete_font_stacks_carry_the_unicode_fallback(self):
        """Every full font stack keeps its non-Latin fallback.

        ``o-add-unicode-support-font()`` walks a list one level deep and inserts
        the fallback ahead of the generic family that terminates it. Nesting a
        list inside the argument, or ending a stack in a generic the function did
        not recognise, made it a silent no-op.
        """
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
        """A repeated family is unreachable and signals a mis-built stack.

        The heading stack read ``"Inter", "SF Pro Display", "Inter", …`` — the
        duplicate was the visible symptom of the nested list, and it made the
        entry between the two copies dead.
        """
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
        """Nothing but emoji fonts may follow the terminating generic family.

        A generic family always resolves, so a real family behind it can only be
        reached per-glyph. Emoji fonts are deliberately placed there; anything
        else is a mistake.
        """
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
