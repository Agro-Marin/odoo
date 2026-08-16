import functools
import logging
import re
from pathlib import Path

from odoo.modules import Manifest
from odoo.tools.assets.esm_registry import external_libs

from . import lint_case
from odoo.addons.base.models.ir_qweb_assets import IrQweb

_logger = logging.getLogger(__name__)

STATIC_IMPORT_RE = re.compile(
    r"""(?:^|[\s;}])(?:import|export)\s+(?:[^'"()]*?\sfrom\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\(\s*["']([^"']+)["']\s*\)""")
COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


@functools.cache
def _addon_js_sources():
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
        broken = []
        self.assertGreater(
            len(_addon_js_sources()), 1000, "the scan reached almost no JS"
        )
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
                if spec in external_libs():
                    continue
                url = IrQweb._specifier_to_static_url(spec)
                if url is None:
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
        self.assertGreater(scanned, 1000, "the scan reached almost no JS")
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
