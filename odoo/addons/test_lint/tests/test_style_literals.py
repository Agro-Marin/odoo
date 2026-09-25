import functools
import re
from collections import defaultdict
from pathlib import Path

from odoo.modules import Manifest

from . import lint_case

HEX_RE = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")

NUMERIC_COLOUR_RE = re.compile(r"\b(?:rgba?|hsla?)\(\s*[\d.]")

BACKDROP_FILTER_RE = re.compile(r"(?<![\w-])(?:-webkit-)?backdrop-filter\s*:")

MATERIAL_FILES = frozenset({"utils.scss"})

BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

LINE_COMMENT_RE = re.compile(r"(?<![:\w])//[^\n]*")

PALETTE_FILES = frozenset(
    {
        "tokens.scss",
        "palette_dark.scss",
        "primitives.scss",
        "primitives.dark.scss",
        "primary_variables.scss",
        "primary_variables.dark.scss",
        "bootstrap_overridden.scss",
        "bootstrap_overridden.dark.scss",
        "bs_functions_overridden.dark.scss",
    }
)

_SKIPPED_PARTS = frozenset({"lib", "tests", "node_modules"})


def is_palette(path: Path) -> bool:
    return path.name in PALETTE_FILES or path.name.endswith(
        (".variables.scss", "_variables.scss")
    )


def _without_comments(text: str) -> str:
    return LINE_COMMENT_RE.sub("", BLOCK_COMMENT_RE.sub(_keep_newlines, text))


def _lines(text: str, *patterns: re.Pattern) -> list[int]:
    text = _without_comments(text)
    return sorted(
        lint_case.line_of(text, match.start())
        for pattern in patterns
        for match in pattern.finditer(text)
    )


def colour_literals(text: str) -> list[int]:
    return _lines(text, HEX_RE, NUMERIC_COLOUR_RE)


def raw_backdrop_filters(text: str) -> list[int]:
    return _lines(text, BACKDROP_FILTER_RE)


def _keep_newlines(match: re.Match) -> str:
    return "\n" * match.group(0).count("\n")


@functools.cache
def _stylesheets() -> tuple[tuple[str, str, Path], ...]:
    sheets = []
    for manifest in Manifest.get_all_addon_manifests():
        static = Path(manifest.path) / "static"
        if manifest.name.startswith("test_") or not static.is_dir():
            continue
        repo = lint_case.repo_of(str(manifest.path))
        for path in sorted(static.rglob("*.*ss")):
            if path.suffix not in (".scss", ".css") or is_palette(path):
                continue
            if _SKIPPED_PARTS.intersection(path.relative_to(static).parts):
                continue
            sheets.append((repo, manifest.name, path))
    return tuple(sheets)


def _findings(sheets, count) -> dict[str, list[str]]:
    findings = defaultdict(list)
    for repo, module, path in sheets:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(Path(Manifest.for_addon(module).path).parent)
        findings[repo].extend(f"{relative}:{line}" for line in count(text))
    return findings


def colour_literal_findings(sheets) -> dict[str, list[str]]:
    return _findings(sheets, colour_literals)


def backdrop_filter_findings(sheets) -> dict[str, list[str]]:
    return _findings(
        (
            (repo, module, path)
            for repo, module, path in sheets
            if not (module == "web" and path.name in MATERIAL_FILES)
        ),
        raw_backdrop_filters,
    )


class TestStyleLiterals(lint_case.LintCase):
    def test_what_counts_as_a_literal(self):
        sample = """
        a { color: #fff; background: #1c1c1eaa; }
        b { color: rgba(0, 0, 0, 0.5); border-color: hsl(210 100% 50%); }
        c { color: rgba($black, 0.5); background: var(--o-bg-view); }
        d { color: #{$link}; }
        /* e { color: #000; } */
        f { color: red; } // g { color: #123456; }
        h { background: url("//cdn.example/x.png"); }
        """
        self.assertEqual(colour_literals(sample), [2, 2, 3, 3])

    def test_colour_literals_only_go_down(self):
        found = colour_literal_findings(_stylesheets())
        for repo in sorted(found):
            with self.subTest(repo=repo):
                self.assert_ratchet(
                    found[repo],
                    f"colour_literals_{repo.replace('-', '_')}",
                    f"hard-coded colour(s) in {repo}'s stylesheets",
                    "Read the colour from the palette: a token "
                    "(o-token(--o-*, $fallback)), a palette variable, or a "
                    "CSS colour function over one. A value only a palette "
                    "file may state goes in the module's *.variables.scss.",
                )

    def test_what_counts_as_a_raw_backdrop_filter(self):
        sample = """
        a { backdrop-filter: blur(4px); }
        b { -webkit-backdrop-filter: blur(4px); }
        c { transition: backdrop-filter 0.2s ease; }
        d { @include o-material("thin"); }
        /* e { backdrop-filter: none; } */
        """
        self.assertEqual(raw_backdrop_filters(sample), [2, 3])

    def test_raw_backdrop_filters_only_go_down(self):
        found = backdrop_filter_findings(_stylesheets())
        for repo in sorted(found):
            with self.subTest(repo=repo):
                self.assert_ratchet(
                    found[repo],
                    f"backdrop_filters_{repo.replace('-', '_')}",
                    f"raw backdrop-filter declaration(s) in {repo}'s stylesheets",
                    'Use a material: @include o-material("ultrathin" | "thin" | '
                    '"regular" | "thick"), or o-glass() for a material over the '
                    "glass background. $o-materials in primary_variables.scss "
                    "is the one definition.",
                )
