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

# The runtime half of the same question. A bundle reached through one of these
# is fetched from `/web/bundle` and served by `assets.getBundle`, which is a
# different code path from `t-call-assets` and was covered by nothing.
# The trailing group captures the options object when there is one, so a
# CSS-only fetch can be told apart: `loadBundle(name, {js: false})` never calls
# `loadESMBundle`, so the ESM half of the payload is never read and the bundle
# needs no ESM declaration at all.
LOAD_BUNDLE_RE = re.compile(
    r"""\b(?:loadBundle|getBundle|preloadBundle)\(\s*["']([\w]+\.[\w.]+)["']"""
    r"""\s*(?:,\s*(?P<options>\{[^{}]*\}))?""",
)
JS_DISABLED_OPTION_RE = re.compile(r"""\bjs\s*:\s*false\b""")

# Page bundles that are also replayed into an iframe at runtime. They must NOT be
# declared `esm.runtime_bundles`: that switches them to the per-file payload,
# which they are not built for -- `_get_esm_bundle_payload("web.assets_frontend")`
# raises `EsbuildBundleError` on relative imports that escape the bundle, because
# esbuild resolves those at build time and per-file serving cannot.
#
# Named rather than counted: a floor of "1" would say nothing about which bundle
# or why, and the next addition would inherit the silence.
RUNTIME_DECLARATION_EXEMPT = {
    # `website_helpers.js` loads it into the builder iframe with
    # `js: loadAssetsFrontendJS`. It is a page bundle being replayed into a
    # second document, not a lazily-loaded feature, and the legacy branch is
    # what serves it there today.
    "web.assets_frontend",
}
# `<LazyComponent bundle="'addon.bundle'"/>` in an inline OWL template, and the
# same attribute in a `.xml` template file.
LAZY_BUNDLE_RE = re.compile(
    r"""\bbundle=["']{1,2}([\w]+\.[\w.]+)["']{1,2}""",
)


class TestEsmBundles(lint_case.LintCase):
    def _scan(self, pattern, glob, transform=None):
        found = {}
        for path in self.iter_module_files(glob):
            try:
                content = Path(path).read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            for match in pattern.finditer(content):
                name = transform(match) if transform else match.group(1)
                if name:
                    found.setdefault(name, path)
        return found

    def _rendered_bundles(self):
        """Bundles a server-rendered template puts on a page."""
        rendered = set()
        for path in self.iter_module_files("*.xml"):
            try:
                content = Path(path).read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            for name, attrs in CALL_ASSETS_RE.findall(content):
                if not JS_DISABLED_RE.search(attrs):
                    rendered.add(name)
        return rendered

    @staticmethod
    def _wants_js(match):
        """False for `loadBundle(name, {js: false})` — a CSS-only fetch."""
        options = match.groupdict().get("options")
        return not (options and JS_DISABLED_OPTION_RE.search(options))

    def _runtime_fetched_bundles(self):
        """Bundles the client fetches at runtime *with their JS*."""
        found = {}
        for glob, pattern in (
            ("*.js", LOAD_BUNDLE_RE),
            ("*.js", LAZY_BUNDLE_RE),
            ("*.xml", LAZY_BUNDLE_RE),
        ):
            scanned = self._scan(
                pattern,
                glob,
                transform=lambda m: m.group(1) if self._wants_js(m) else None,
            )
            for name, path in scanned.items():
                found.setdefault(name, path)
        return found

    def _declaration_index(self):
        """(declared ESM bundle names, own files per bundle, include edges, addon roots)."""
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
        """The lazy half of the sibling above, which reads XML and nothing else.

        `loadBundle` resolves *successfully* against an undeclared bundle: the
        server builds it as a legacy concatenation, every module-syntax file is
        replaced by a `console.error` stub, and the caller gets a fulfilled
        promise carrying nothing. Nothing throws, the page returns 200, and the
        component that awaited the bundle dies later on a registry lookup —
        which is why this needs a gate rather than a test per feature.
        """
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
        """Declared ESM is not enough — the route reads `runtime_bundle_names`.

        `/web/bundle` serves the ESM payload only for a bundle in
        `esm.runtime_bundles` (or, equivalently, a `dynamic_children` child). A
        bundle in `esm.bundles` alone still falls through to the legacy branch,
        which is the same console.error stub with none of the signals: the
        manifest looks right, and the sibling test above passes.
        """
        registry = esm_registry()
        fetched = self._runtime_fetched_bundles()
        _declared, own_files, includes, addon_dirs = self._declaration_index()
        offenders = []
        candidates = set(fetched) - registry.runtime_bundle_names
        for bundle in sorted(candidates - RUNTIME_DECLARATION_EXEMPT):
            if bundle not in registry.bundles:
                continue  # the sibling test above owns this case
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
