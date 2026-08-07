import functools
import logging
import re
from pathlib import Path

from odoo.libs.constants import ODOO_EXTERNAL_LIBS
from odoo.modules import Manifest

from . import lint_case
from odoo.addons.base.models.ir_qweb_assets import IrQweb

_logger = logging.getLogger(__name__)

# `import x from "spec"`, `export {x} from "spec"`, bare `import "spec"`, and
# `import("spec")` -- the last covering both dynamic imports and the
# `@type {import("spec").T}` JSDoc form, which is the same syntax.
STATIC_IMPORT_RE = re.compile(
    r"""(?:^|[\s;}])(?:import|export)\s+(?:[^'"()]*?\sfrom\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\(\s*["']([^"']+)["']\s*\)""")
#: Block and line comments, so a JSDoc `@type {import("./x").T}` is not read as
#: a runtime import: it names a type, is never fetched, and needs no extension.
COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


@functools.cache
def _addon_js_sources():
    """``(path, source)`` for every non-vendored JS file under an addon.

    Vendored libraries are third-party sources shipped verbatim; they do not
    use the ``@addon`` convention and must not be edited to satisfy it.

    Cached: both tests below need the same 9 174 files, and reading them is the
    larger half of what either one costs.
    """
    return tuple(_read_addon_js())


def _read_addon_js():
    for manifest in Manifest.all_addon_manifests():
        static_root = Path(manifest.path) / "static"
        if not static_root.is_dir():
            continue
        for path in static_root.rglob("*.js"):
            if "lib" in path.relative_to(static_root).parts[:1]:
                continue
            try:
                yield path, path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue


class TestEsmSpecifiers(lint_case.LintCase):
    def test_relative_specifiers_carry_their_extension(self):
        """Every relative import must name a file that exists, extension included.

        The two rendering paths resolve these differently, so an extensionless
        relative import links in production and 404s in debug. esbuild bundles
        with node resolution and supplies the ``.js``; debug/fallback rendering
        serves each module's raw source and leaves relative specifiers to the
        *browser* (``discover_transitive_import_specifiers``: "the browser
        resolves a relative reference against the importing module's URL, no map
        entry needed"), and the browser guesses no extension. The static handler
        then 404s, and since the debug page imports the whole bundle from one
        ``<script type="module">``, that single 404 aborts the entire graph:
        a blank web client, one console line, no server-side trace.

        Its sibling above cannot see this. A relative specifier never reaches
        ``_specifier_to_static_url``, precisely because the browser resolves it
        without the import map -- so the addon convention has nothing to say
        about it, and the resolution has to be done here, against disk.

        Directory imports are rejected for the same reason: esbuild resolves
        ``./foo`` to ``foo/index.js``, the browser does not.
        """
        broken = []
        for path, source in _addon_js_sources():
            code = COMMENT_RE.sub(" ", source)
            specs = set(STATIC_IMPORT_RE.findall(code))
            specs |= set(DYNAMIC_IMPORT_RE.findall(code))
            for spec in specs:
                if not spec.startswith("."):
                    continue
                target = (path.parent / spec).resolve()
                if not target.is_file():
                    broken.append((path, spec, target))

        if broken:
            details = "\n".join(
                f"  {path}\n      imports {spec!r} -> no such file {target}"
                for path, spec, target in sorted(broken)
            )
            self.fail(
                f"{len(broken)} relative ESM specifier(s) that only esbuild can "
                f"resolve. Each one serves a blank web client under "
                f"?debug=assets. Write the path as it is served, extension "
                f"included:\n{details}"
            )

    def test_esm_specifiers_resolve(self):
        """Every ``@addon/...`` import in JS must point at a file that exists.

        This is a build-breaking class of error, not a per-file one. esbuild
        fails the *whole bundle* on one unresolvable specifier, and a failed
        build degrades to an empty bundle (``ir_qweb_assets``, logged at
        WARNING and nowhere else) -- so a single stale import in any addon on
        the path serves a blank web client to every database that happens to
        include it. Nothing else catches this: the importing module need not be
        installed, need not have JS tests, and its own suite would pass anyway
        because the failure is in the bundle, not in the module.

        It is exactly what a fork's own refactors produce. Moving a module
        inside ``web`` is invisible to the addons that import it, and the
        breakage surfaces as a blank page in an unrelated repo.

        The ``@addon/...`` -> path convention comes from
        ``IrQweb._specifier_to_static_url`` rather than being reimplemented, so
        it cannot drift (``../lib/`` and ``../tests/`` escapes included). The
        directory form is then accepted on top of it: that helper answers for
        the import map, which needs one exact URL, while esbuild resolves a
        specifier naming a directory to its ``index.js`` -- and ~40 modules
        under ``point_of_sale`` and ``l10n_it_pos`` import that way.

        Specifiers naming an addon that is not on this addons_path are skipped:
        the bundle can only ever contain modules it can see.
        """
        addon_paths = {
            manifest.name: Path(manifest.path)
            for manifest in Manifest.all_addon_manifests()
        }
        broken = []
        scanned = 0

        for path, source in _addon_js_sources():
            scanned += 1
            specs = set(STATIC_IMPORT_RE.findall(source))
            specs |= set(DYNAMIC_IMPORT_RE.findall(source))
            for spec in specs:
                if spec in ODOO_EXTERNAL_LIBS:
                    continue
                url = IrQweb._specifier_to_static_url(spec)
                if url is None:
                    # Bare or reserved @odoo/* namespace: resolved by the
                    # loader, not by a file on disk.
                    continue
                addon, _, relative = url.lstrip("/").partition("/")
                root = addon_paths.get(addon)
                if root is None:
                    continue
                target = root / relative
                index = target.with_suffix("") / "index.js"
                if not target.is_file() and not index.is_file():
                    broken.append((path, spec, f"{addon}/{relative}"))

        _logger.info("checked ESM specifiers in %s js files", scanned)
        if broken:
            details = "\n".join(
                f"  {path}\n      imports {spec!r} -> no such file {target}"
                for path, spec, target in sorted(broken)
            )
            self.fail(
                f"{len(broken)} unresolvable ESM specifier(s). Each one fails the "
                f"entire asset bundle it lands in, which serves a blank web "
                f"client:\n{details}"
            )
