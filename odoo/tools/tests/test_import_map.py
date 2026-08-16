import ast
import base64
import hashlib
import json
import re
import unittest
from pathlib import Path

from odoo.tools.assets import esm_registry
from odoo.tools.assets.esm_registry import external_libs, invalidate_esm_registry
from odoo.tools.assets.import_map import import_map_for

_TAG_BODY = re.compile(r'<script type="importmap">(?P<body>.*?)</script>', re.DOTALL)


def _find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "odoo-bin").exists():
            return candidate
    raise RuntimeError("could not locate the repo root above test_import_map.py")


_REPO_ROOT = _find_repo_root()

_OVERRIDE_DIRS = (_REPO_ROOT / "addons/web/static/lib/hoot/tests",)


def _declared_external_libs() -> dict[str, str]:
    """Read ``esm.external_libs`` off the bundled manifests, without Odoo.

    The registry's own builder walks ``Manifest.all_addon_manifests()``, which
    imports ``odoo.modules`` and from there the whole ORM — not available to
    this suite, which runs against the ``odoo.libs`` leaves under the
    DB-free bootstrap. Parsing the literals is the same information.
    """
    declared: dict[str, str] = {}
    for manifest in sorted(_REPO_ROOT.glob("addons/*/__manifest__.py")):
        try:
            data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
        if isinstance(data, dict):
            declared.update((data.get("esm") or {}).get("external_libs") or {})
    return declared


def setUpModule():
    """Seed the registry so ``import_map_for`` resolves without a database."""
    esm_registry._cache[0] = esm_registry.EsmRegistry(
        bundles=frozenset(),
        dynamic_children={},
        import_map_includes={},
        secondary_import_map_includes={},
        dynamic_bundle_names=frozenset(),
        import_map_included_bundles=frozenset(),
        external_libs=_declared_external_libs(),
    )


def tearDownModule():
    invalidate_esm_registry()


def _sha256_expr(body: str) -> str:
    return (
        f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"
    )


class TestImportMapFor(unittest.TestCase):
    def test_resolves_urls_from_the_external_libs_registry(self):
        map_ = import_map_for("@popperjs/core")
        self.assertEqual(
            json.loads(_TAG_BODY.search(map_.script_tag)["body"]),
            {"imports": {"@popperjs/core": external_libs()["@popperjs/core"]}},
        )

    def test_hash_covers_exactly_the_emitted_inline_body(self):
        for specs in (("@popperjs/core",), ("luxon", "dompurify"), ("@odoo/owl",)):
            with self.subTest(specs=specs):
                map_ = import_map_for(*specs)
                body = _TAG_BODY.search(map_.script_tag)["body"]
                self.assertEqual(map_.csp_hash, _sha256_expr(body))

    def test_hash_matches_a_browser_computed_value(self):
        body = '{"imports": {"@popperjs/core": "/web/static/lib/popper/popper.esm.js"}}'
        self.assertEqual(
            _sha256_expr(body),
            "'sha256-L6D+Pkeols3LJsHdaiuYaUiHBEoDxCFlqxK/S6jJ96I='",
        )

    def test_output_is_deterministic_and_order_independent(self):
        self.assertEqual(
            import_map_for("luxon", "@popperjs/core"),
            import_map_for("@popperjs/core", "luxon"),
        )

    def test_unregistered_specifier_is_rejected(self):
        with self.assertRaises(KeyError) as caught:
            import_map_for("@popperjs/core", "left-pad")
        self.assertIn("left-pad", str(caught.exception))


class TestHardcodedImportMaps(unittest.TestCase):
    def _hardcoded_maps(self):
        for pattern in ("addons/**/*.html", "addons/**/*.xml"):
            for path in _REPO_ROOT.glob(pattern):
                if any(path.is_relative_to(d) for d in _OVERRIDE_DIRS):
                    continue
                try:
                    source = path.read_text(encoding="utf-8")
                except OSError, UnicodeDecodeError:
                    continue
                if 'type="importmap"' not in source:
                    continue
                for match in _TAG_BODY.finditer(source):
                    try:
                        imports = json.loads(match["body"]).get("imports", {})
                    except json.JSONDecodeError:
                        continue
                    yield path, imports

    def test_hardcoded_maps_agree_with_the_registry(self):
        registered = external_libs()
        checked = 0
        for path, imports in self._hardcoded_maps():
            for spec, url in imports.items():
                if spec not in registered:
                    continue
                checked += 1
                self.assertEqual(
                    url,
                    registered[spec],
                    f"{path.relative_to(_REPO_ROOT)} pins a stale URL for {spec!r}; "
                    f"prefer odoo.tools.assets.import_map.import_map_for()",
                )
        self.assertGreater(
            checked, 0, "import-map scan matched nothing — check the glob"
        )


class TestIotHomepagePlaceholder(unittest.TestCase):
    """The IoT box is the only live consumer of `import_map_for`, and its pages
    fail silently in both directions.

    `homepage.py::_render_page` substitutes `IMPORT_MAP_PLACEHOLDER` and sets a
    CSP whose `script-src` carries the map's hash. Drop the placeholder from a
    page that needs one and `str.replace` finds nothing: no import map is
    emitted, the CSP still allows the script that is not there, and the page
    ships with `@popperjs/core` unresolvable. Nothing else in the tree would
    notice — the module is `installable: False` and runs only as a
    `server_wide_modules` entry on the box image.
    """

    VIEWS = _REPO_ROOT / "addons/iot_drivers/views"
    CONTROLLER = _REPO_ROOT / "addons/iot_drivers/controllers/homepage.py"

    def _placeholder(self):
        source = self.CONTROLLER.read_text(encoding="utf-8")
        match = re.search(r'IMPORT_MAP_PLACEHOLDER = "([^"]+)"', source)
        self.assertIsNotNone(match, "homepage.py no longer defines the placeholder")
        return match.group(1)

    def test_a_page_loading_bootstrap_carries_the_placeholder(self):
        """`bootstrap.esm.js` imports Popper by bare specifier — the one thing
        on the box that needs a map at all, per `_import_map`'s own comment."""
        placeholder = self._placeholder()
        checked = 0
        for page in sorted(self.VIEWS.glob("*.html")):
            source = page.read_text(encoding="utf-8")
            if "bootstrap.esm.js" not in source:
                continue
            checked += 1
            self.assertIn(
                placeholder,
                source,
                f"{page.name} loads bootstrap.esm.js, which imports "
                f"'@popperjs/core' by bare specifier, but carries no import-map "
                f"placeholder — the page would ship without one",
            )
        self.assertGreater(checked, 0, "no IoT page loads bootstrap — check the glob")

    def test_the_substituted_page_matches_the_csp_hash(self):
        """The round trip: what is substituted is what the hash covers."""
        placeholder = self._placeholder()
        map_ = import_map_for("@popperjs/core")
        for page in sorted(self.VIEWS.glob("*.html")):
            source = page.read_text(encoding="utf-8")
            if placeholder not in source:
                continue
            rendered = source.replace(placeholder, map_.script_tag)
            bodies = _TAG_BODY.findall(rendered)
            self.assertEqual(
                len(bodies), 1, f"{page.name} rendered {len(bodies)} import maps"
            )
            self.assertEqual(map_.csp_hash, _sha256_expr(bodies[0]))
