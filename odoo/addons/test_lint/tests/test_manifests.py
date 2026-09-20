import logging
import tempfile
import textwrap
from pathlib import Path

from odoo import release
from odoo.modules.module import _DEFAULT_MANIFEST, Manifest, _normalize_manifest
from odoo.tests.common import BaseCase, no_retry
from odoo.tools import mute_logger

from . import _checker_manifest, _sort_manifests
from .lint_case import LintCase, is_core_path

_logger = logging.getLogger(__name__)


class ManifestLinter(LintCase):
    def test_manifests(self):
        manifests = list(Manifest.get_all_addon_manifests())
        checker = _checker_manifest.ManifestChecker(
            addon_dirs={m.name: Path(m.path) for m in manifests},
            series=release.major_version,
        )
        checked = 0
        shape = []
        value = []
        for manifest in manifests:
            if not is_core_path(str(manifest.path)):
                continue
            checked += 1
            path = Path(manifest.path) / "__manifest__.py"
            outcome = _sort_manifests.sort_manifest(path, dry_run=True)
            if outcome is None:
                shape.append(f"{manifest.name}: the fixer declines it")
            elif outcome:
                shape.append(f"{manifest.name}: the fixer would rewrite it")
            value.extend(
                checker.findings(manifest.name, manifest.declared, Path(manifest.path))
            )
        _logger.info("checked %s manifests", checked)
        self.assertTrue(checked, "the scan reached no manifests at all")

        self.assert_ratchet(
            value,
            "lint_manifest_value",
            "manifest value(s) the fixer cannot decide: an unknown or deprecated "
            "key, a wrong type, a path that matches no file, a dependency on no "
            "addons path, a hook `__init__.py` does not bind",
            "Correct the value, or drop the key.",
        )
        self.assert_ratchet(
            shape,
            "lint_manifest_shape",
            "manifest(s) not in canonical shape: key order, a restated default, "
            "stray whitespace, a set-valued bundle, an escaped non-ASCII string",
            "Run `odoo/addons/test_lint/tests/_sort_manifests.py <dir>` from the "
            "repository root.",
        )

    def test_known_licenses_are_the_selection_ir_module_module_offers(self):
        with self.superuser_env() as env:
            offered = env["ir.module.module"]._fields["license"].get_values(env)
        self.assertEqual(set(offered), _checker_manifest.KNOWN_LICENSES)

    def test_the_vocabulary_covers_every_default_the_loader_knows(self):
        self.assertEqual(
            set(_DEFAULT_MANIFEST)
            - _checker_manifest.KNOWN_KEYS
            - set(_sort_manifests.DEPRECATED_KEYS),
            set(),
            "a key the loader defaults must be either ordered or deprecated",
        )


@no_retry
class TestManifestChecker(BaseCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.module = self.root / "thing"
        self.module.mkdir()
        (self.module / "__init__.py").write_text(
            "from . import models\nfrom .hooks import post_init\n"
        )
        (self.module / "data").mkdir()
        (self.module / "data" / "thing_data.xml").write_text("<odoo/>")
        (self.module / "demo").mkdir()
        (self.module / "demo" / "thing_demo.xml").write_text("<odoo/>")
        (self.module / "static" / "description").mkdir(parents=True)
        (self.module / "static" / "description" / "icon.png").write_bytes(b"")
        (self.root / "base" / "data").mkdir(parents=True)
        (self.root / "base" / "data" / "ir_module_category_data.xml").write_text(
            textwrap.dedent("""
                <odoo>
                    <record id="module_category_hidden" model="ir.module.category">
                        <field name="name">Technical</field>
                    </record>
                    <record id="module_category_sales" model="ir.module.category">
                        <field name="name">Sales</field>
                    </record>
                    <record id="module_category_sales_sales" model="ir.module.category">
                        <field name="name">Sales</field>
                        <field name="parent_id" ref="module_category_sales"/>
                    </record>
                </odoo>
            """)
        )
        self.checker = _checker_manifest.ManifestChecker(
            addon_dirs={"thing": self.module, "base": self.root / "base"},
            series="19.0",
        )

    def _findings(self, **data) -> list[str]:
        base = {
            "name": "Thing",
            "version": "19.0.1.0.0",
            "category": "Sales/Sales",
            "author": "AgroMarin",
            "license": "LGPL-3",
            "depends": ["base"],
        }
        return self.checker.findings("thing", {**base, **data}, self.module)

    def test_a_canonical_manifest_has_no_finding(self):
        self.assertEqual(
            self._findings(
                data=["data/thing_data.xml"],
                demo=["demo/thing_demo.xml"],
                icon="/thing/static/description/icon.png",
                post_init_hook="post_init",
                countries=["mx", "us"],
                external_dependencies={
                    "python": ["python-stdnum>=1.0"],
                    "apt": {"python-stdnum": "python3-stdnum"},
                },
                assets={
                    "web.assets_backend": [
                        "thing/static/src/**/*",
                        ("remove", "thing/static/src/legacy/*"),
                        ("after", "web/static/src/a.js", "thing/static/src/b.js"),
                    ]
                },
            ),
            [],
        )

    def test_every_rule_fires_on_its_own_shape(self):
        cases = {
            "unknown key `maintaner`": {"maintaner": "x"},
            "key `init_xml` is deprecated and read by nothing; use `data`": {
                "init_xml": []
            },
            "`name` is empty": {"name": "  "},
            "`sequence` is str, expected int": {"sequence": "10"},
            "`application` is int, expected bool": {"application": 1},
            "`depends` is not a list of str": {"depends": "base"},
            "`version` '1.a' does not parse; the loader marks the module uninstallable": {
                "version": "1.a"
            },
            "`version` '18.0.1.0.0' belongs to another series; the loader marks the module uninstallable": {
                "version": "18.0.1.0.0"
            },
            "`license` 'MIT' is not one `ir.module.module` offers": {"license": "MIT"},
            "`category` 'Sales//Sales' has an empty segment": {
                "category": "Sales//Sales"
            },
            "`category` 'Fleet' starts a root no `ir_module_category_data.xml` declares": {
                "category": "Fleet"
            },
            "`website` 'www.example.com' is not an http(s) URL": {
                "website": "www.example.com"
            },
            "`depends` names the module itself": {"depends": ["base", "thing"]},
            "`depends` lists 'base' twice": {"depends": ["base", "base"]},
            "`depends` names 'nowhere', which is on no addons path": {
                "depends": ["base", "nowhere"]
            },
            "`auto_install` trigger 'sale' is not in `depends`": {
                "auto_install": ["sale"]
            },
            "`external_dependencies` kind 'deb' is read by nothing; the kinds are python, bin and apt": {
                "external_dependencies": {"deb": {}}
            },
            "`external_dependencies.apt` names 'zeep', which `external_dependencies.python` does not declare": {
                "external_dependencies": {"python": [], "apt": {"zeep": "python3-zeep"}}
            },
            "`countries` entry 'MEX' is not a two-letter code": {"countries": ["MEX"]},
            "`data` entry 'data/missing.xml' matches no file": {
                "data": ["data/missing.xml"]
            },
            "`demo` lists 'data/thing_data.xml' already listed under `data`": {
                "data": ["data/thing_data.xml"],
                "demo": ["data/thing_data.xml"],
            },
            "`demo` entry 'data/thing_data.xml' does not live in `demo/`": {
                "demo": ["data/thing_data.xml"]
            },
            "`data` entry 'demo/thing_demo.xml' is a demo file listed as data": {
                "data": ["demo/thing_demo.xml"]
            },
            "`icon` '/thing/static/description/logo.png' matches no file": {
                "icon": "/thing/static/description/logo.png"
            },
            "`post_init_hook` names 'setup', which `__init__.py` does not bind": {
                "post_init_hook": "setup"
            },
            "`assets` bundle 'backend' is not `<module>.<bundle>`": {
                "assets": {"backend": []}
            },
            "`assets` bundle 'web.assets_backend' directive 'delete' is unknown": {
                "assets": {"web.assets_backend": [("delete", "x")]}
            },
            "`assets` bundle 'web.assets_backend' directive 'after' takes 2 path(s), got ('after', 'x')": {
                "assets": {"web.assets_backend": [("after", "x")]}
            },
        }
        for expected, data in cases.items():
            with self.subTest(expected=expected):
                self.assertIn(f"thing: {expected}", self._findings(**data))

    def test_a_single_country_module_is_expected_to_say_l10n(self):
        self.assertIn(
            "thing: specific to the single country 'mx' but has no `l10n` in its name",
            self._findings(countries=["mx"]),
        )
        self.assertEqual(
            self.checker.findings(
                "l10n_thing",
                {"name": "T", "category": "Sales", "countries": ["mx"]},
                self.module,
            ),
            [],
        )

    def test_a_star_import_in_init_waives_the_hook_check(self):
        (self.module / "__init__.py").write_text("from .hooks import *\n")
        self.assertEqual(self._findings(post_init_hook="anything"), [])

    def test_requirement_names_are_compared_normalised(self):
        for spec, name in (
            ("python-stdnum>=1.0", "python-stdnum"),
            ("Python_Stdnum[extra]; python_version > '3'", "python-stdnum"),
            ("zeep", "zeep"),
        ):
            self.assertEqual(_checker_manifest.requirement_name(spec), name)

    def test_category_roots_are_the_parentless_declared_records(self):
        self.assertEqual(
            self.checker.category_roots,
            {"module_category_hidden", "module_category_sales"},
        )
        self.assertEqual(self._findings(category="Hidden/Tools"), [])


@no_retry
class TestManifestNormalize(BaseCase):
    maxDiff = None

    def test_a_restated_default_is_dropped_and_version_is_kept(self):
        self.assertEqual(
            _sort_manifests.normalize(
                "thing",
                {
                    "installable": True,
                    "application": False,
                    "auto_install": False,
                    "version": "1.0",
                    "data": [],
                    "name": "Thing",
                    "category": "Uncategorized",
                    "sequence": 100,
                },
            ),
            {"name": "Thing", "version": "1.0"},
        )

    def test_a_default_of_another_type_is_kept_for_the_checker(self):
        self.assertEqual(
            _sort_manifests.normalize("thing", {"application": 0, "sequence": True}),
            {"sequence": True, "application": 0},
        )

    def test_an_empty_auto_install_list_is_not_the_default(self):
        self.assertEqual(
            _sort_manifests.normalize("thing", {"auto_install": []}),
            {"auto_install": []},
        )

    def test_whitespace_and_case_are_normalised(self):
        self.assertEqual(
            _sort_manifests.normalize(
                "thing",
                {
                    "name": " Thing ",
                    "summary": "\n   two\n words  ",
                    "description": "\n    \n",
                    "website": " ",
                    "url": " https://example.com ",
                    "countries": ["MX", "us"],
                    "icon": "/thing/static/description/icon.png",
                    "assets": {"web.assets_backend": {"b", "a"}, "web.x": ("c",)},
                },
            ),
            {
                "name": "Thing",
                "summary": "two words",
                "url": "https://example.com",
                "countries": ["mx", "us"],
                "assets": {"web.assets_backend": ["a", "b"], "web.x": ["c"]},
            },
        )

    @mute_logger("odoo.modules.module")
    def test_dropping_defaults_changes_nothing_the_loader_sees(self):
        declared = {
            "name": "Thing",
            "installable": True,
            "application": False,
            "auto_install": False,
            "depends": [],
            "data": [],
            "demo": [],
            "sequence": 100,
            "category": "Uncategorized",
            "external_dependencies": {},
            "assets": {},
        }
        self.assertEqual(
            _normalize_manifest("thing", _sort_manifests.normalize("thing", declared)),
            _normalize_manifest("thing", declared),
        )


@no_retry
class TestManifestVocabulary(BaseCase):
    def test_every_ordered_key_is_ordered_once(self):
        order = _sort_manifests.MANIFEST_KEY_ORDER
        self.assertEqual(len(order), len(set(order)))
        self.assertFalse(set(order) & set(_sort_manifests.DEPRECATED_KEYS))

    def test_unknown_keys_sort_after_known_ones(self):
        self.assertEqual(
            _sort_manifests.expected_key_order(["zzz", "depends", "aaa", "name"]),
            ["name", "depends", "aaa", "zzz"],
        )

    def test_the_cli_and_the_gate_read_the_same_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "__manifest__.py"
            path.write_text(
                textwrap.dedent("""
                    # header
                    {
                        "name": "x",
                        "depends": ["base"],
                    }
                """).lstrip()
            )
            self.assertEqual(
                _sort_manifests.read_manifest(path),
                {"name": "x", "depends": ["base"]},
            )
            path.write_text("not a dict\n")
            self.assertIsNone(_sort_manifests.read_manifest(path))
