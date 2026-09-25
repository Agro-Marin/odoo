import logging
from pathlib import Path
from unittest.mock import patch

from odoo.modules import Manifest
from odoo.tools.assets.esm_graph import addon_specifier_to_url
from odoo.tools.assets.esm_registry import external_libs

from . import _js_sources, _specifier_renames, lint_case

_logger = logging.getLogger(__name__)

_REMOTE_PREFIXES = ("http://", "https://", "data:", "blob:")
# Standalone pages that render their own import map: the bare specifiers it
# maps resolve there and nowhere else.
_PAGE_MAPPED_BARE = {
    "web/src/public/database_manager": {"bootstrap"},  # its .qweb.html
}


def _addon_js_sources():
    return _js_sources.addon_js_outside_lib()


def _unresolved_specifiers(sources):
    addon_paths = {
        manifest.name: Path(manifest.path)
        for manifest in Manifest.get_all_addon_manifests()
    }
    broken = []
    for source_addon, path, source in sources:
        # JSDoc import() expressions resolve types, not runtime JS assets.
        for spec in _js_sources.specifiers(source):
            if spec in external_libs() or spec.startswith(_REMOTE_PREFIXES):
                continue
            if spec.startswith("/"):
                # an absolute URL (/web/static/lib/...) is served as is
                addon, _, relative = spec.lstrip("/").partition("/")
                root = addon_paths.get(addon)
                if root is None or not (root / relative).is_file():
                    broken.append((path, spec, f"no such file {spec.lstrip('/')}"))
                continue
            if not spec.startswith(("@", ".")):
                page_mapped = _PAGE_MAPPED_BARE.get(
                    _js_sources.module_key(source_addon, path), ()
                )
                if spec not in page_mapped:
                    # only an import map resolves a bare specifier
                    broken.append(
                        (path, spec, "bare specifier outside esm.external_libs")
                    )
                continue
            url = addon_specifier_to_url(spec)
            if url is None:
                continue
            addon, _, relative = url.lstrip("/").partition("/")
            root = addon_paths.get(addon)
            if root is None:
                continue
            target = root / relative
            index = target.with_suffix("") / "index.js"
            if not target.is_file() and not index.is_file():
                broken.append(
                    (
                        path,
                        spec,
                        f"no such file {addon}/{relative}"
                        + _specifier_renames.hint(spec),
                    )
                )
    return broken


class TestEsmSpecifiers(lint_case.LintCase):
    def test_specifiers_distinguish_code_from_comments_and_strings(self):
        cases = [
            ('const url = "https://example.test"; import("@web/real");', {"@web/real"}),
            ('const a = "/*"; import("@web/real"); const b = "*/";', {"@web/real"}),
            (
                '/** @type {import("@web/types").T} */ import("@web/real");',
                {"@web/real"},
            ),
            (
                "const code = 'import(\"@web/fake\")'; export * from '@web/real';",
                {"@web/real"},
            ),
            (
                'const text = `import("@web/fake") ${import("@web/real")}`;',
                {"@web/real"},
            ),
            (
                'const regex = /import\\("@web\\/fake"\\)/; import("@web/real");',
                {"@web/real"},
            ),
            (
                '// import("@web/fake")\nimport /* comment */ ("@web/real");',
                {"@web/real"},
            ),
            (
                'import { x } from "@web/static"; export { y } from "@web/export"; import("@web/dynamic");',
                {"@web/static", "@web/export", "@web/dynamic"},
            ),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                actual = _js_sources.specifiers(source)
                _logger.debug("ESM lexer probe: source=%r imports=%s", source, actual)
                self.assertEqual(actual, expected)

    def test_specifier_check_fails_when_lexer_is_unavailable(self):
        with patch.object(_js_sources, "lex_module", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "module lexer is unavailable"):
                _js_sources.specifiers('import "@web/missing";')

    def test_relative_specifiers_carry_their_extension(self):
        broken = []
        self.assertGreater(
            len(_addon_js_sources()), 1000, "the scan reached almost no JS"
        )
        for _addon, path, source in _addon_js_sources():
            for spec in _js_sources.specifiers(source):
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

    def test_bare_and_absolute_specifiers_are_checked(self):
        web = Path(Manifest.for_addon("web").path)
        source = (
            'import "not-a-declared-lib";\n'
            'import "/web/static/lib/no_such_lib.js";\n'
            'import "/web/static/lib/owl/owl.es.js";\n'
            'import "https://example.test/remote.js";\n'
            'import { t } from "@web/core/no_such_module";\n'
        )
        broken = _unresolved_specifiers(
            [
                ("web", web / "static/src/fake_probe.js", source),
                (
                    "web",
                    web / "static/src/public/database_manager.js",
                    'import "bootstrap";',
                ),
            ]
        )
        self.assertEqual(
            sorted(spec for _path, spec, _why in broken),
            [
                "/web/static/lib/no_such_lib.js",
                "@web/core/no_such_module",
                "not-a-declared-lib",
            ],
        )

    def test_the_rename_table_points_at_live_modules(self):
        # a stale row would send the next upstream import to a dead path
        for old, new in _specifier_renames.RENAMED.items():
            with self.subTest(old=old):
                self.assertEqual(
                    _unresolved_specifiers(
                        [("web", Path("probe.js"), f'import "{new}";')]
                    ),
                    [],
                )
                self.assertTrue(
                    _unresolved_specifiers(
                        [("web", Path("probe.js"), f'import "{old}";')]
                    ),
                    "the old specifier resolves again: drop its row",
                )

    def test_esm_specifiers_resolve(self):
        sources = _addon_js_sources()
        scanned = len(sources)
        broken = _unresolved_specifiers(sources)

        _logger.info("checked ESM specifiers in %s js files", scanned)
        self.assertGreater(scanned, 1000, "the scan reached almost no JS")
        if broken:
            details = "\n".join(
                f"  {path}\n      imports {spec!r} -> {why}"
                for path, spec, why in sorted(broken)
            )
            self.fail(
                f"{len(broken)} unresolvable ESM specifier(s). Each one fails the "
                f"entire asset bundle it lands in, which serves a blank web "
                f"client:\n{details}"
            )
