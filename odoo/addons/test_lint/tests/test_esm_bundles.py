import logging
import re
from pathlib import Path

from odoo.modules import Manifest
from odoo.tools.assets.esm_graph import has_module_syntax

from . import lint_case

_logger = logging.getLogger(__name__)

# `<t t-call-assets="bundle.name" .../>`, capturing the trailing attributes so
# a stylesheet-only render (`t-js="False"`) can be told apart.
CALL_ASSETS_RE = re.compile(
    r"""t-call-assets=["']([^"']+)["']([^>]*)""",
)
JS_DISABLED_RE = re.compile(r"""t-js=["']False["']""")


class TestEsmBundles(lint_case.LintCase):
    def _rendered_bundles(self):
        """Bundle names reached by ``t-call-assets`` with JS enabled."""
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

    def test_rendered_bundles_carrying_esm_are_declared(self):
        """A bundle serving ES-module sources must be declared under ``esm``.

        An undeclared bundle is assembled as a legacy concatenation, and
        ``JsPipeline._module_syntax_error_stub`` replaces every module-syntax
        file in it with a ``console.error``. The page it serves then boots into
        nothing. It is a whole-page outage that leaves the HTTP response at 200
        and shows up only as server ERRORs nobody reads -- 307 of them per load,
        in the case that prompted this test (`pos_preparation_display.assets`).

        Only bundles reached by ``t-call-assets`` are checked. Bundles that
        exist purely to be ``('include', ...)``-ed into another one are
        assembled as part of their parent and never take the legacy path on
        their own, so ~4200 files in `web.assets_backend` are not a finding.
        A ``t-js="False"`` render asks for the stylesheet only and never emits
        the JS, so it is not one either.
        """
        manifests = list(Manifest.all_addon_manifests())
        addon_dirs = {m.name: Path(m.path) for m in manifests}

        declared = set()
        own_files = {}
        includes = {}
        for manifest in manifests:
            esm = manifest.get("esm") or {}
            declared.update(esm.get("bundles") or ())
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

        def module_files(bundle, seen):
            """Module-syntax .js the bundle carries, following ``include``."""
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
                found.extend(module_files(child, seen))
            return found

        rendered = self._rendered_bundles()
        offenders = []
        for bundle in sorted(rendered - declared):
            files = module_files(bundle, set())
            if files:
                offenders.append((bundle, files))

        _logger.info(
            "checked %s rendered bundles (%s declared ESM)",
            len(rendered),
            len(declared),
        )
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
