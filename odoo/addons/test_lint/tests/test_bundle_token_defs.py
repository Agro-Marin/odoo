import logging
import re
from pathlib import Path

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)

#: The file that turns the Sass palette into `--o-*` custom properties.
TOKENS = "web/static/src/scss/tokens.scss"

#: A `var()` with no fallback -- the form that has nothing to fall back on.
#: The name may be interpolated, because that is how every ramp token is read:
#: `rgb(var(--o-record-color-#{$size}-chip-bg-rgb))`.
VAR_RE = re.compile(r"var\(\s*(--o-[\w$#{}-]+)\s*\)")

#: A Sass interpolation, on either side of the read/publish comparison. What it
#: stands for is one loop index or map key -- `1`, `900`, `danger` -- so it is
#: matched by `\w+` rather than anything hyphenated, which keeps
#: `o-#{$-name}-text` from claiming every `--o-*-text` in the codebase.
INTERPOLATION_RE = re.compile(r"#\{[^}]*\}")

#: A double-quoted `o-*` string in `tokens.scss`: both the keys of the map
#: `o-token-set()` builds and the names handed to `print-variable()`.
TOKEN_LITERAL_RE = re.compile(r'"(o-[\w$#{}-]*)"')

#: The head of a `@mixin`/`@function` definition, up to its opening brace.
DEFINITION_RE = re.compile(r"@(?:mixin|function)\b[^{}]*\{")

#: Bundles that read a palette token from somewhere other than `tokens.scss`.
ALLOWED = set()


@tagged("post_install", "-at_install")
class TestBundleTokenDefs(lint_case.LintCase):
    """A bundle that reads a palette token must also carry ``tokens.scss``.

    ``tokens.scss`` is what turns the Sass palette into ``--o-*``, and it does
    not ride every bundle. So converting a declaration from ``$o-gray-900`` to
    ``var(--o-gray-900)`` is correct in some bundles and silently wrong in
    others: an unresolvable ``var()`` does not fall back to the colour, it
    makes the whole declaration invalid at computed-value time, and the
    property takes its initial value instead.

    Nothing else catches this. The file compiles, every manifest path exists,
    and a colour comparison across the bundles that do carry ``tokens.scss``
    reports no change -- the affected bundle is never looked at. It was found
    on ``mail.assets_public``, ``portal.assets_chatter``,
    ``portal.assets_chatter_style`` and ``web.report_assets_common``, which
    between them style the public discuss view, the portal chatter and every
    rendered report.

    Reads the bundle's *file list* rather than its compiled CSS: assembling a
    bundle is cheap and needs no attachment, while compiling one inside a test
    transaction cannot persist and so returns whatever happened to be in the
    database already.

    Only bundles belonging to installed modules are assembled, so this is a
    floor rather than a proof -- run it on a database with a broad install.

    Which names count is read out of ``tokens.scss`` rather than listed here.
    A list has to be right twice -- once when a token is added and once when a
    reader appears -- and it was not: ``--o-record-color-*`` was excluded as
    having "its own publisher", which is true of ``--o-cc*`` and false of the
    ramp, whose 336 tokens ``tokens.scss`` is the only source of. Those are the
    tokens ``badge``, ``tags_list``, ``colorlist`` and the calendars read, and
    they ride ``web._assets_core`` into every bundle that globs it -- which is
    exactly the shape of the defect this test exists for.
    """

    @staticmethod
    def _name_pattern(name):
        """Turn a published token name into what a read of it has to match.

        Either half of a name can be interpolated -- ``o-gray-#{$-step}``,
        ``o-record-color-#{$-i}-subtle-rgb`` -- so the literal chunks are
        matched exactly and each interpolation stands for the one loop index or
        map key it expands to.
        """
        chunks = INTERPOLATION_RE.split(name)
        return re.compile("--" + r"\w+".join(re.escape(chunk) for chunk in chunks))

    @classmethod
    def published_token_patterns(cls):
        """Every custom property ``tokens.scss`` publishes, as patterns.

        Read out of the publisher so a token added there is guarded by
        definition. Both spellings count: the keys of the map ``o-token-set()``
        builds, and the names handed to ``print-variable()`` for the ramps.
        """
        path = Path(cls._module_roots(["web"])[0]) / TOKENS.split("/", 1)[1]
        names = set(TOKEN_LITERAL_RE.findall(path.read_text(encoding="utf-8")))
        assert names, f"no token names found in {TOKENS}"
        return [cls._name_pattern(name) for name in sorted(names)]

    @staticmethod
    def _emits_css(text):
        """Whether the file produces any rule of its own.

        A file holding only variables and ``@mixin``/``@function`` definitions
        ships no declaration, so it cannot ship an invalid one either: the
        obligation belongs to whoever calls the mixin, in the bundle that
        carries the call. ``web_gantt``'s ``gantt_view.variables.scss`` is the
        case that makes this necessary -- it reads the record ramp inside
        ``o-gantt-subdle()`` and rides ``web._assets_primary_variables``, so it
        reaches every bundle with helpers, twenty-two of which publish no
        tokens and none of which invoke it.

        Definitions inside an emitting file still count: those are called where
        they are written, as in ``calendar_common_popover.scss``.
        """
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
            # `x` stands for whatever the reader interpolates; the pattern
            # accepts one word there, so the two sides meet on the same shape.
            if any(p.fullmatch(INTERPOLATION_RE.sub("x", name)) for p in patterns)
        }

    def test_the_inventory_matches_how_tokens_are_read(self):
        """The two halves have to agree on interpolation, or this goes vacuous.

        Every ramp token is published with an interpolated name and read with
        one, and neither side is spelled the way a plain string is. The pairing
        that was in place before matched neither: a literal name list could not
        describe ``o-record-color-#{$-i}``, and a `[\\w-]+` read pattern could
        not match ``var(--o-record-color-#{$size}-rgb)``.
        """
        pattern = self._name_pattern("o-record-color-#{$-i}-chip-bg-rgb")
        self.assertTrue(pattern.fullmatch("--o-record-color-x-chip-bg-rgb"))
        self.assertTrue(self._name_pattern("o-gray-#{$-step}").fullmatch("--o-gray-x"))
        self.assertTrue(self._name_pattern("o-white").fullmatch("--o-white"))
        self.assertFalse(self._name_pattern("o-white").fullmatch("--o-white-ish"))
        # `o-#{$-name}-text` must not claim every hyphenated `--o-*-text`.
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
        """The group that carries three quarters of the dark palette.

        It was the one the previous inventory left out, and it is the one whose
        readers travel furthest: ``badge``, ``tags_list`` and ``colorlist`` ride
        ``web._assets_core`` into every bundle that globs it.
        """
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
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            for bundle in self.served_bundle_names(env):
                try:
                    files = env["ir.qweb"]._get_asset_bundle(bundle, css=True).files
                except Exception as exc:
                    # A bundle that will not assemble is TestAssetPathsExist's
                    # business, not this one's.
                    skipped.append(f"{bundle} ({type(exc).__name__})")
                    continue
                if not files:
                    # Counting these as checked is how this test goes vacuous:
                    # a bundle assembles to nothing when the registry is not
                    # fully loaded, which is why this runs post_install.
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
        if empty:
            _logger.info("assembled to nothing: %s", ", ".join(empty))
        if skipped:
            # Named rather than counted: a bundle that quietly stops assembling
            # would otherwise read as one with nothing to report.
            _logger.info("did not assemble, so unchecked: %s", ", ".join(skipped))
        self.assertFalse(
            offenders,
            f"{len(offenders)} file(s) read a palette token in a bundle that "
            f"does not carry {TOKENS}. Add it to the bundle, or read the Sass "
            f"variable instead where the bundle has only one palette to "
            f"follow:\n  " + "\n  ".join(offenders),
        )
