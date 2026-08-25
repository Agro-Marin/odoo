import functools
import logging
import re
from pathlib import Path

from odoo.modules import Manifest
from odoo.tools.assets.esm_graph import has_module_syntax
from odoo.tools.assets.esm_registry import esm_registry

from . import lint_case

_logger = logging.getLogger(__name__)

CALL_ASSETS_RE = re.compile(
    r"""t-call-assets=["']([^"']+)["']([^>]*)""",
)
JS_DISABLED_RE = re.compile(r"""t-js=["']False["']""")

LOAD_BUNDLE_RE = re.compile(
    r"""\b(?:loadBundle|getBundle|preloadBundle)\(\s*["']([\w]+\.[\w.]+)["']"""
    r"""\s*(?:,\s*(?P<options>\{[^{}]*\}))?""",
)
JS_DISABLED_OPTION_RE = re.compile(r"""\bjs\s*:\s*false\b""")

RUNTIME_DECLARATION_EXEMPT = {
    "web.assets_frontend",
}
LAZY_BUNDLE_RE = re.compile(
    r"""\bbundle=["']{1,2}([\w]+\.[\w.]+)["']{1,2}""",
)


#: Every source this class scans, read once. The two runtime tests below each
#: called `_runtime_fetched_bundles()`, which makes three passes -- `*.js` twice
#: and `*.xml` once -- so the identical 18,953-file sweep ran twice per run:
#: 37,906 of the 56,754 reads the JS gates performed between them. `_declaration_index`
#: walked every manifest once per test on top of that.
@functools.cache
def _sources(glob: str) -> tuple[tuple[str, str], ...]:
    out = []
    for path in lint_case.iter_module_files(glob):
        try:
            out.append((path, Path(path).read_text(encoding="utf-8")))
        except OSError, UnicodeDecodeError:
            continue
    return tuple(out)


def _scan(pattern, glob, transform=None):
    found = {}
    for path, content in _sources(glob):
        for match in pattern.finditer(content):
            name = transform(match) if transform else match.group(1)
            if name:
                found.setdefault(name, path)
    return found


def _wants_js(match):
    options = match.groupdict().get("options")
    return not (options and JS_DISABLED_OPTION_RE.search(options))


@functools.cache
def _rendered_bundles() -> frozenset[str]:
    rendered = set()
    for _path, content in _sources("*.xml"):
        for name, attrs in CALL_ASSETS_RE.findall(content):
            if not JS_DISABLED_RE.search(attrs):
                rendered.add(name)
    return frozenset(rendered)


@functools.cache
def _runtime_fetched_bundles() -> dict[str, str]:
    found = {}
    for glob, pattern in (
        ("*.js", LOAD_BUNDLE_RE),
        ("*.js", LAZY_BUNDLE_RE),
        ("*.xml", LAZY_BUNDLE_RE),
    ):
        scanned = _scan(
            pattern,
            glob,
            transform=lambda m: m.group(1) if _wants_js(m) else None,
        )
        for name, path in scanned.items():
            found.setdefault(name, path)
    return found


@functools.cache
def _declaration_index():
    manifests = list(Manifest.all_addon_manifests())
    addon_dirs = {m.name: Path(m.path) for m in manifests}

    declared = set()
    own_files = {}
    includes = {}
    for manifest in manifests:
        esm = manifest.get("esm") or {}
        declared.update(esm.get("bundles") or ())
        declared.update(esm.get("standalone_bundles") or ())
        for key in (
            "dynamic_children",
            "import_map_includes",
            "secondary_import_map_includes",
        ):
            for parent, children in (esm.get(key) or {}).items():
                declared.add(parent)
                declared.update(children)
        for bundle, entries in (manifest.get("assets") or {}).items():
            for entry in entries:
                if isinstance(entry, (list, tuple)):
                    if len(entry) == 2 and entry[0] == "include":
                        includes.setdefault(bundle, set()).add(entry[1])
                elif isinstance(entry, str):
                    own_files.setdefault(bundle, []).append(entry)
    return declared, own_files, includes, addon_dirs


class TestEsmBundles(lint_case.LintCase):
    _rendered_bundles = staticmethod(_rendered_bundles)
    _runtime_fetched_bundles = staticmethod(_runtime_fetched_bundles)
    _declaration_index = staticmethod(_declaration_index)

    @staticmethod
    def _module_files(bundle, own_files, includes, addon_dirs, seen):
        if bundle in seen:
            return []
        seen.add(bundle)
        found = []
        for spec in own_files.get(bundle, ()):
            addon, _, relative = spec.partition("/")
            root = addon_dirs.get(addon)
            if root is None or not relative:
                continue
            if any(ch in relative for ch in "*?["):
                try:
                    candidates = list(root.glob(relative))
                except ValueError, OSError:
                    continue
            else:
                candidates = [root / relative]
            for candidate in candidates:
                if candidate.suffix != ".js" or not candidate.is_file():
                    continue
                try:
                    content = candidate.read_text(encoding="utf-8")
                except OSError, UnicodeDecodeError:
                    continue
                if has_module_syntax(content):
                    found.append(candidate)
        for child in includes.get(bundle, ()):
            found.extend(
                TestEsmBundles._module_files(
                    child, own_files, includes, addon_dirs, seen
                )
            )
        return found

    def _offenders(self, candidates):
        declared, own_files, includes, addon_dirs = self._declaration_index()
        offenders = []
        for bundle in sorted(set(candidates) - declared):
            files = self._module_files(bundle, own_files, includes, addon_dirs, set())
            if files:
                offenders.append((bundle, files))
        return offenders, len(declared)

    def test_rendered_bundles_carrying_esm_are_declared(self):
        rendered = self._rendered_bundles()
        offenders, n_declared = self._offenders(rendered)
        _logger.info(
            "checked %s rendered bundles (%s declared ESM)", len(rendered), n_declared
        )
        self.assertTrue(rendered, "no bundle is rendered — the scan found none")
        if offenders:
            details = "\n".join(
                f"  {bundle}: {len(files)} module-syntax file(s), e.g. {files[0].name}"
                for bundle, files in offenders
            )
            self.fail(
                f"{len(offenders)} rendered bundle(s) carry ES-module sources "
                f"without an 'esm' declaration in their module's manifest. Every "
                f"such file is replaced by a console.error stub, so the page "
                f"serves a blank screen:\n{details}"
            )

    def test_runtime_fetched_bundles_carrying_esm_are_declared(self):
        fetched = self._runtime_fetched_bundles()
        offenders, n_declared = self._offenders(fetched)
        _logger.info(
            "checked %s runtime-fetched bundles (%s declared ESM)",
            len(fetched),
            n_declared,
        )
        self.assertTrue(
            fetched, "no bundle is fetched at runtime — the scan found none"
        )
        if offenders:
            details = "\n".join(
                f"  {bundle}: {len(files)} module-syntax file(s), "
                f"e.g. {files[0].name} — cited by {fetched[bundle]}"
                for bundle, files in offenders
            )
            self.fail(
                f"{len(offenders)} bundle(s) fetched at runtime carry ES-module "
                f"sources without an 'esm' declaration in their module's "
                f"manifest. loadBundle() will resolve successfully and deliver "
                f"console.error stubs instead of the modules:\n{details}"
            )

    def test_runtime_fetched_bundles_are_declared_as_such(self):
        registry = esm_registry()
        fetched = self._runtime_fetched_bundles()
        _declared, own_files, includes, addon_dirs = self._declaration_index()
        offenders = []
        candidates = set(fetched) - registry.runtime_bundle_names
        for bundle in sorted(candidates - RUNTIME_DECLARATION_EXEMPT):
            if bundle not in registry.bundles:
                continue
            if self._module_files(bundle, own_files, includes, addon_dirs, set()):
                offenders.append(bundle)
        if offenders:
            details = "\n".join(
                f"  {bundle} — cited by {fetched[bundle]}" for bundle in offenders
            )
            self.fail(
                f"{len(offenders)} bundle(s) are fetched at runtime and declared "
                f"under 'esm.bundles', but not under 'esm.runtime_bundles', so "
                f"/web/bundle serves them through the legacy branch:\n{details}"
            )
        self.assertEqual(
            sorted(RUNTIME_DECLARATION_EXEMPT - set(fetched)),
            [],
            "an exemption that no call site needs any more — drop it",
        )
