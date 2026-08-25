import logging
import re
from pathlib import Path

from odoo.tests import tagged

from . import lint_case

_logger = logging.getLogger(__name__)

TOKENS = "web/static/src/scss/tokens.scss"

VAR_RE = re.compile(r"var\(\s*(--o-[\w$#{}-]+)\s*\)")

INTERPOLATION_RE = re.compile(r"#\{[^}]*\}")

TOKEN_LITERAL_RE = re.compile(r'"(o-[\w$#{}-]*)"')

DEFINITION_RE = re.compile(r"@(?:mixin|function)\b[^{}]*\{")

ALLOWED = set()


@tagged("post_install", "-at_install")
class TestBundleTokenDefs(lint_case.LintCase):
    @staticmethod
    def _name_pattern(name):
        chunks = INTERPOLATION_RE.split(name)
        return re.compile("--" + r"\w+".join(re.escape(chunk) for chunk in chunks))

    @classmethod
    def published_token_patterns(cls):
        path = Path(cls._module_roots(["web"])[0]) / TOKENS.split("/", 1)[1]
        names = set(TOKEN_LITERAL_RE.findall(path.read_text(encoding="utf-8")))
        assert names, f"no token names found in {TOKENS}"
        return [cls._name_pattern(name) for name in sorted(names)]

    @staticmethod
    def _emits_css(text):
        stripped, cursor = [], 0
        while (match := DEFINITION_RE.search(text, cursor)) is not None:
            stripped.append(text[cursor : match.start()])
            depth, index = 1, match.end()
            while depth and index < len(text):
                depth += {"{": 1, "}": -1}.get(text[index], 0)
                index += 1
            cursor = index
        stripped.append(text[cursor:])
        return "{" in "".join(stripped)

    def _palette_reads(self, path, patterns):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return set()
        if not self._emits_css(text):
            return set()
        return {
            name
            for name in VAR_RE.findall(text)
            if any(p.fullmatch(INTERPOLATION_RE.sub("x", name)) for p in patterns)
        }

    def test_the_inventory_matches_how_tokens_are_read(self):
        pattern = self._name_pattern("o-record-color-#{$-i}-chip-bg-rgb")
        self.assertTrue(pattern.fullmatch("--o-record-color-x-chip-bg-rgb"))
        self.assertTrue(self._name_pattern("o-gray-#{$-step}").fullmatch("--o-gray-x"))
        self.assertTrue(self._name_pattern("o-white").fullmatch("--o-white"))
        self.assertFalse(self._name_pattern("o-white").fullmatch("--o-white-ish"))
        theme_text = self._name_pattern("o-#{$-name}-text")
        self.assertTrue(theme_text.fullmatch("--o-danger-text"))
        self.assertFalse(theme_text.fullmatch("--o-cw-popover-text"))
        self.assertEqual(
            sorted(
                VAR_RE.findall(
                    "a { color: rgb(var(--o-record-color-#{$size}-chip-bg-rgb)); }"
                    "b { color: var(--o-gray-900); }"
                    "c { color: var(--o-gray-900, #fff); }"
                )
            ),
            ["--o-gray-900", "--o-record-color-#{$size}-chip-bg-rgb"],
        )

    def test_the_ramp_is_in_the_inventory(self):
        patterns = self.published_token_patterns()
        for name in (
            "--o-record-color-3",
            "--o-record-color-3-chip-bg-rgb",
            "--o-record-color-12-on-rgb",
            "--o-gray-500",
            "--o-tint-target",
            "--o-danger-text",
        ):
            self.assertTrue(
                any(p.fullmatch(name) for p in patterns),
                f"{name} is published by {TOKENS} but not guarded by this test",
            )

    def test_palette_tokens_are_published_in_every_bundle_reading_them(self):
        patterns = self.published_token_patterns()
        offenders = []
        assembled = 0
        skipped = []
        empty = []
        cache = {}
        with self.superuser_env() as env:
            for bundle in self.served_bundle_names(env):
                try:
                    files = env["ir.qweb"]._get_asset_bundle(bundle, css=True).files
                except Exception as exc:
                    skipped.append(f"{bundle} ({type(exc).__name__})")
                    continue
                if not files:
                    empty.append(bundle)
                    continue
                assembled += 1
                urls = {(f["url"] or "").lstrip("/") for f in files}
                if TOKENS in urls:
                    continue
                reads = {}
                for spec in files:
                    filename = spec.get("filename")
                    if not filename or not filename.endswith((".scss", ".css")):
                        continue
                    if filename not in cache:
                        cache[filename] = self._palette_reads(filename, patterns)
                    if cache[filename]:
                        reads[(spec["url"] or "").lstrip("/")] = sorted(cache[filename])
                for url, names in sorted(reads.items()):
                    if (bundle, url) in ALLOWED:
                        continue
                    offenders.append(f"{bundle}: {url} reads {', '.join(names)}")

        _logger.info("assembled %s bundles with files", assembled)
        self.assertFalse(
            skipped,
            f"{len(skipped)} served bundle(s) did not assemble, so this check "
            f"never looked at them. `TestBundlesAssemble` owns that failure; "
            f"fix it there first:\n  " + "\n  ".join(skipped),
        )
        self.assertFalse(
            empty,
            f"{len(empty)} served bundle(s) assembled to no files at all, which "
            f"is what a partially-loaded registry looks like -- this class runs "
            f"post_install for that reason:\n  " + "\n  ".join(empty),
        )
        self.assertFalse(
            offenders,
            f"{len(offenders)} file(s) read a palette token in a bundle that "
            f"does not carry {TOKENS}. Add it to the bundle, or read the Sass "
            f"variable instead where the bundle has only one palette to "
            f"follow:\n  " + "\n  ".join(offenders),
        )
