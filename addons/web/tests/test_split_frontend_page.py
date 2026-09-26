import json
import pathlib
import re

from markupsafe import Markup

from odoo.tests.common import HttpCase, TransactionCase, tagged
from odoo.tools.assets.esm_registry import esm_registry
from odoo.tools.misc import file_path

MINIMAL = "web.assets_frontend_minimal"
LAZY = "web.assets_frontend_lazy"

_IMPORT_MAP_RE = re.compile(
    r'<script type="importmap" data-bundle="([^"]*)">(.*?)</script>', re.DOTALL
)
_MODULE_SCRIPT_RE = re.compile(
    r'<script type="module" src="([^"]+)" data-bridge="([^"]+)"'
)


@tagged("-at_install", "post_install", "web_assets")
class TestSplitFrontendPage(HttpCase):
    """`web.assets_frontend_minimal` and `web.assets_frontend_lazy` are one
    page cut in two: each module of the minimal half is evaluated by that half
    alone, and the page carries one import map holding both halves' entries."""

    def _pages(self):
        installed = self.env["ir.asset"]._get_addons_installed()
        pages = [("/web/login", None)]
        if "website" in installed:
            pages.append(("/", None))
        if "portal" in installed:
            pages.append(("/my", "admin"))
        return pages

    def _html(self, url, login):
        if login:
            self.authenticate(login, login)
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200, url)
        return response.text

    def _minimal_sources(self):
        bundle = self.env["ir.qweb"]._get_asset_bundle(MINIMAL, css=False, js=True)
        return {asset.url: asset.module_path for asset in bundle.native_modules}

    def _evaluations(self, html, sources):
        counts = dict.fromkeys(sources.values(), 0)
        scripts = _MODULE_SCRIPT_RE.findall(html)
        self.assertTrue(scripts, "fixture: the page serves compiled module scripts")
        sizes = {
            url: pathlib.Path(file_path(url.lstrip("/"))).stat().st_size
            for url in sources
        }
        for src, _bundle in scripts:
            meta = self.url_open(src.removesuffix(".esm.js") + ".meta.json")
            self.assertEqual(meta.status_code, 200, src)
            for path, info in meta.json()["inputs"].items():
                for url, spec in sources.items():
                    # a mirror stub carries the real path, not the real bytes
                    if path.endswith(url) and info["bytes"] == sizes[url]:
                        counts[spec] += 1
        return counts

    def test_each_minimal_module_is_evaluated_once_per_page(self):
        sources = self._minimal_sources()
        self.assertIn("@web/session", sources.values())
        for url, login in self._pages():
            with self.subTest(page=url):
                counts = self._evaluations(self._html(url, login), sources)
                self.assertEqual(
                    {spec: n for spec, n in counts.items() if n != 1},
                    {},
                    "a module of the minimal half is evaluated by another "
                    "bundle of the page too",
                )

    def test_the_page_carries_one_import_map_named_after_its_page_bundle(self):
        IrQweb = self.env["ir.qweb"]
        own = {}
        for bundle in (MINIMAL, LAZY):
            pre, _post = IrQweb._get_native_module_nodes(bundle, page=False)
            for node in pre:
                if IrQweb._is_import_map_node(node):
                    own[bundle] = json.loads(node[1]["text"])["imports"]
        self.assertTrue(
            any(spec.startswith("@web_tour/") for spec in own[LAZY]),
            "fixture: the lazy half maps web_tour's specifiers",
        )
        for url, login in self._pages():
            with self.subTest(page=url):
                html = self._html(url, login)
                maps = _IMPORT_MAP_RE.findall(html)
                self.assertEqual(len(maps), 1, "Firefox honours the first map only")
                stamp, text = maps[0]
                self.assertEqual(stamp, LAZY, "dynamic children are declared on it")
                imports = json.loads(text)["imports"]
                self.assertFalse(set(own[MINIMAL]) - set(imports))
                self.assertEqual(
                    {
                        spec: imports.get(spec)
                        for spec, target in own[LAZY].items()
                        if imports.get(spec) != target
                    },
                    {},
                    "the minimal half shadows what the lazy half maps",
                )
                order = [bundle for _src, bundle in _MODULE_SCRIPT_RE.findall(html)]
                self.assertLess(
                    order.index(MINIMAL),
                    order.index(LAZY),
                    "the lazy half reads what the minimal half registers",
                )

    def test_the_split_page_boots_in_the_browser(self):
        specs = sorted(
            self.env["ir.qweb"]._get_secondary_shared_specs(
                LAZY, self.env["ir.asset"]._prepare_assets_params()
            )
        )
        self.assertIn("@web/session", specs)
        for url, login in self._pages():
            with self.subTest(page=url):
                self.browser_js(
                    url,
                    """
                    const maps = document.querySelectorAll('script[type="importmap"]');
                    const missing = %s.filter((spec) => !odoo.loader.modules.has(spec));
                    if (maps.length !== 1) {
                        console.error(`${maps.length} import maps on the page`);
                    } else if (missing.length) {
                        console.error("not registered: " + missing.join(", "));
                    } else {
                        console.log("test successful");
                    }
                    """
                    % json.dumps(specs),
                    "document.body.getAttribute('is-ready') === 'true'",
                    login=login,
                )

    def test_the_lazy_half_is_a_page_not_a_satellite(self):
        registry = esm_registry()
        self.assertIn(LAZY, registry.page_secondaries)
        self.assertIn(MINIMAL, registry.secondary_parents[LAZY])
        self.assertNotIn("web.assets_tests", registry.page_secondaries)
        import_map = {}
        self.env["ir.qweb"]._merge_secondary_import_maps(
            MINIMAL,
            import_map,
            self.env["ir.asset"]._prepare_assets_params(),
            debug_assets=False,
        )
        self.assertEqual(
            import_map,
            {},
            "the lazy half maps itself and its satellites, after its bridges",
        )


@tagged("-at_install", "post_install", "web_assets")
class TestPageImportMapMerge(TransactionCase):
    def _merge(self, html, emitted, stamp=None):
        return self.env["ir.qweb"]._merge_page_import_maps(Markup(html), emitted, stamp)

    def test_later_maps_fold_into_the_first_in_document_order(self):
        html = (
            '<head><script type="importmap" data-bundle="a">{"imports": {"x": "/1"}}'
            '</script>\n<script type="module" src="/a.js"></script>\n'
            '<script type="importmap" data-bundle="b">{"imports": {"x": "/2", "y": "/3"}}'
            "</script></head>"
        )
        merged = self._merge(html, 2, stamp="b")
        maps = _IMPORT_MAP_RE.findall(merged)
        self.assertEqual(len(maps), 1)
        self.assertEqual(maps[0][0], "b")
        self.assertEqual(json.loads(maps[0][1])["imports"], {"x": "/1", "y": "/3"})
        self.assertLess(merged.index('type="importmap"'), merged.index('type="module"'))
        self.assertIsInstance(merged, Markup)

    def test_a_map_it_did_not_emit_leaves_the_page_alone(self):
        html = (
            '<script type="importmap" data-bundle="a">{"imports": {}}</script>'
            '<script type="importmap" data-bundle="b">{"imports": {}}</script>'
            '<script type="importmap" data-bundle="c">{"imports": {}}</script>'
        )
        self.assertEqual(self._merge(html, 2), html)

    def test_the_page_is_named_after_the_half_declaring_dynamic_children(self):
        IrQweb = self.env["ir.qweb"]
        params = self.env["ir.asset"]._prepare_assets_params()
        self.assertTrue(IrQweb._declares_dynamic_children(LAZY, params))
        self.assertFalse(IrQweb._declares_dynamic_children(MINIMAL, params))
        html = (
            '<script type="importmap" data-bundle="a">{"imports": {}}</script>'
            '<script type="importmap" data-bundle="b">{"imports": {}}</script>'
        )
        self.assertEqual(
            _IMPORT_MAP_RE.findall(self._merge(html, 2))[0][0],
            "a",
            "without a bundle declaring children, the first map names the page",
        )

    def test_a_lone_map_takes_the_page_name_and_no_map_is_no_change(self):
        html = (
            '<script type="importmap" data-bundle="a">{"imports": {"x": "/1"}}</script>'
        )
        merged = self._merge(html, 1, stamp="b")
        self.assertEqual(
            _IMPORT_MAP_RE.findall(merged), [("b", '{"imports": {"x": "/1"}}')]
        )
        self.assertEqual(self._merge("<p/>", 0, stamp="b"), "<p/>")
