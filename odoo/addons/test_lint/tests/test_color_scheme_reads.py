import logging
import re

from odoo.libs.lint import scan_regex_patterns
from odoo.modules import get_resource_from_path

from . import lint_case

_logger = logging.getLogger(__name__)

#: `cookie.get("color_scheme")` and `cookie.set("color_scheme", …)`, plus the
#: raw `document.cookie` spelling that covers both.
#:
#: One definition each, compiled for the self-test below and handed to the Rust
#: scanner as text: a self-test that validates a *copy* stops answering for the
#: pattern the scan actually runs the moment either is edited.
COOKIE_GET_PAT = r"""cookie\.get\(\s*["']color_scheme["']\s*\)"""
COOKIE_SET_PAT = r"""cookie\.set\(\s*["']color_scheme["']"""
RAW_COOKIE_PAT = r"""document\.cookie[^;\n]*color_scheme"""
PATTERNS = (COOKIE_GET_PAT, COOKIE_SET_PAT, RAW_COOKIE_PAT)

REGEXES = tuple(re.compile(pattern) for pattern in PATTERNS)

#: The only file that may touch the cookie. It carries both halves -- the read
#: and the publication -- so everything else goes through `colorScheme` in
#: `@web/core/color_scheme`, in either direction.
ALLOWED_SUFFIXES = ("/web/static/src/core/color_scheme.js",)


class TestColorSchemeReads(lint_case.LintCase):
    """The colour scheme must be read through @web/core/color_scheme.

    The cookie is a transport detail — how the server hands the resolved
    scheme over at boot. Reading it directly spreads its name, its storage and
    its value set across every module that only wants to know whether the UI is
    dark, and leaves nothing able to observe a change. It also invites the two
    failures this rule exists to prevent: comparing against ``"dark"`` by hand
    (so an unexpected value silently reads as light), and reading at module
    scope, where no later correction can reach the value.

    "Nothing able to observe a change" is why the accessor also owns
    publication: a reader that goes through it can be told, and
    ``useColorScheme`` tells it. That is not reachable from a module that
    reaches past to the cookie.

    Writes are held to the same list, because a second writer is the way the
    cookie and the setting it mirrors come apart. The value is
    ``ir_http.color_scheme``'s to decide — it resolves the *setting* above the
    cookie — and every template that serves the web client sets it from there,
    so a caller that has just changed the setting needs only to have the page
    re-served. The one answer the server cannot give is ``system``, and the
    inline resolver in ``webclient_bootstrap`` gives that one, in the template
    rather than here.
    """

    def check_text(self, text):
        """Return the 1-based line numbers of direct cookie uses in *text*."""
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
            self._module_roots(),
            [".js"],
            list(PATTERNS),
            ["node_modules", "__pycache__"],
        )

        failures = 0
        for path, line, _pat_idx, matched_text in results:
            if path.endswith(ALLOWED_SUFFIXES):
                continue
            # Vendored code we do not author; it cannot import from @web.
            if "/static/lib/" in path:
                continue
            if "/static/tests/" in path:
                continue

            failures += 1
            try:
                mod, relative_path, _ = get_resource_from_path(path)
            except TypeError:
                mod, relative_path = "?", path

            _logger.error(
                "Direct color_scheme cookie use in `%s/%s` at line %s: %s. "
                "Read it through `colorScheme` from @web/core/color_scheme "
                "(`colorScheme.isDark`, `colorScheme.current`); to change it, "
                "save the setting and have the page re-served.",
                mod,
                relative_path,
                line,
                matched_text.strip(),
            )

        self.assertEqual(
            failures,
            0,
            "The colour scheme cookie is @web/core/color_scheme's to read "
            "and the server's to write; see the errors above.",
        )
