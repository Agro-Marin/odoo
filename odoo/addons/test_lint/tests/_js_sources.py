"""Every addon's JavaScript, read once.

`test_esm_specifiers` and `test_orphan_test_registrations` each walked
`<addon>/static/**/*.js` and read every file, with two near-identical walkers and
a **character-identical** import regex between them. Counting reads per test:

    18964  TestEsmBundles.test_runtime_fetched_bundles_carrying_esm_are_declared
    18953  TestEsmBundles.test_runtime_fetched_bundles_are_declared_as_such
     6587  TestEsmSpecifiers.test_esm_specifiers_resolve
     6700  TestOrphanTestRegistrations.test_no_registration_module_is_orphaned
     5550  TestEsmBundles.test_rendered_bundles_carrying_esm_are_declared
    56754  total, over a file union of about 12,250

`TestEsmSpecifiers` already had the answer -- its second test reads 0 files,
because `_addon_js_sources` is `functools.cache`d. This generalises that.
"""

import functools
import re
from pathlib import Path

from odoo.modules import Manifest

#: A static or dynamic ESM specifier. One copy: `test_esm_specifiers` and
#: `test_orphan_test_registrations` carried this same pattern character for
#: character, which is two places for one answer to drift apart.
STATIC_IMPORT_RE = re.compile(
    r"""(?:^|[\s;}])(?:import|export)\s+(?:[^'"()]*?\sfrom\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\(\s*["']([^"']+)["']\s*\)""")
COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


@functools.cache
def addon_js() -> tuple[tuple[str, Path, str], ...]:
    """`(addon, path, source)` for every `.js` under an addon's `static/`."""
    out = []
    for manifest in Manifest.all_addon_manifests():
        static_root = Path(manifest.path) / "static"
        if not static_root.is_dir():
            continue
        for path in sorted(static_root.rglob("*.js")):
            try:
                out.append((manifest.name, path, path.read_text(encoding="utf-8")))
            except OSError, UnicodeDecodeError:
                continue
    return tuple(out)


@functools.cache
def addon_js_outside_lib() -> tuple[tuple[str, Path, str], ...]:
    """The same, without vendored `static/lib/`, which nobody here authored."""
    return tuple(
        (addon, path, source)
        for addon, path, source in addon_js()
        if not _under_static_lib(addon, path)
    )


def _under_static_lib(addon: str, path: Path) -> bool:
    parts = path.as_posix().split("/static/", 1)
    return len(parts) == 2 and parts[1].split("/", 1)[0] == "lib"


def specifiers(source: str, *, strip_comments: bool = False) -> set[str]:
    code = COMMENT_RE.sub(" ", source) if strip_comments else source
    return set(STATIC_IMPORT_RE.findall(code)) | set(DYNAMIC_IMPORT_RE.findall(code))


def module_key(addon: str, path: Path) -> str | None:
    """`<addon>/<posix path under static/>`, without the .js suffix."""
    parts = path.as_posix().split("/static/", 1)
    return f"{addon}/{parts[1].removesuffix('.js')}" if len(parts) == 2 else None
