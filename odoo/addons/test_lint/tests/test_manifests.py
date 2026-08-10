import logging
from pathlib import PurePosixPath

from odoo.modules.module import _DEFAULT_MANIFEST, Manifest
from odoo.tools.misc import file_path

from . import _sort_manifests
from .lint_case import LintCase, is_core_path

_logger = logging.getLogger(__name__)

MANIFEST_KEYS = {
    "name",
    "icon",
    "addons_path",
    "author",
    "license",
    *_DEFAULT_MANIFEST,
    "contributors",
    "maintainer",
    "url",
    "price",
    "currency",
    "support",
    "live_test_url",
}


class ManifestLinter(LintCase):
    def test_manifests(self):
        checked = 0
        violations = []
        self.advisories = []
        for manifest in Manifest.all_addon_manifests():
            if not is_core_path(str(manifest.path)):
                continue
            checked += 1
            for check in (
                self._test_manifest_keys,
                self._test_manifest_key_order,
                self._test_manifest_values,
            ):
                try:
                    check(manifest)
                except AssertionError as exc:
                    violations.append(
                        f"{manifest.name}: {str(exc).splitlines()[0][:160]}"
                    )
        _logger.info("checked %s manifests", checked)
        self.assertTrue(checked, "the scan reached no manifests at all")

        self.assert_ratchet(
            self.advisories,
            0,
            "manifest value(s) of the wrong type, or an icon/countries entry "
            "that does not hold up",
            "Correct the value, or drop the key.",
        )
        self.assert_ratchet(
            violations,
            MANIFEST_FLOOR,
            "manifest(s) with unknown keys, non-canonical key order or "
            "redundant default values",
            "Run `_sort_manifests.py` from the repository root, then lower the floor.",
        )

    def _test_manifest_keys(self, manifest_data: Manifest):
        manifest_keys = manifest_data._Manifest__manifest_content.keys()
        unknown_keys = manifest_keys - MANIFEST_KEYS
        self.assertEqual(
            unknown_keys,
            set(),
            f"Unknown manifest keys in module {manifest_data.name!r}. Either there are typos or they must be white listed.",
        )

    def _test_manifest_key_order(self, manifest_data: Manifest):
        actual = list(manifest_data._Manifest__manifest_content.keys())
        expected = _sort_manifests.expected_key_order(actual)
        self.assertEqual(
            actual,
            expected,
            f"Manifest keys are out of canonical order in module {manifest_data.name!r}.\n"
            "Run `./venv/odoo/bin/python core/odoo/addons/test_lint/tests/_sort_manifests.py` to fix.",
        )

    def _test_manifest_values(self, manifest_data: Manifest):
        module = manifest_data.name
        verified_keys = [
            "application",
            "auto_install",
            "summary",
            "description",
            "author",
            "demo",
            "data",
            "test",
        ]

        if len(manifest_data.get("countries", [])) == 1 and "l10n" not in module:
            self.advisories.append(
                f"{module}: specific to the single country "
                f"{manifest_data['countries'][0]!r} but has no `l10n` in its name"
            )

        redundant = []
        for key, value in manifest_data._Manifest__manifest_content.items():
            if key in _DEFAULT_MANIFEST:
                if key in verified_keys and value == _DEFAULT_MANIFEST[key]:
                    redundant.append(key)

                expected_type = type(_DEFAULT_MANIFEST[key])
                if not isinstance(value, expected_type):
                    if key != "auto_install":
                        self.advisories.append(
                            f"{module}: {key} is {type(value).__name__}, "
                            f"expected {expected_type.__name__}"
                        )
                    elif not isinstance(value, list):
                        self.advisories.append(
                            f"{module}: auto_install is {type(value).__name__}, "
                            f"expected bool or list"
                        )
                elif key == "countries":
                    self._test_manifest_countries_value(module, value)
            elif key == "icon":
                redundant.extend(self._test_manifest_icon_value(module, value))

        self.assertFalse(
            redundant,
            f"Manifest key(s) {', '.join(redundant)} set to the default value for "
            f"module {module!r}. Remove them: a key that restates the default is "
            f"noise, and it hides the ones that do carry a decision.",
        )

    def _test_manifest_icon_value(self, module, value):
        if not isinstance(value, str):
            self.advisories.append(
                f"{module}: icon is {type(value).__name__}, expected str"
            )
            return []
        if value == f"/{module}/static/description/icon.png":
            return ["icon"]
        if not value:
            self.advisories.append(f"{module}: icon is empty; drop the key")
            return []
        path_parts = value.split("/")
        try:
            file_path(str(PurePosixPath(*path_parts[1:])))
        except FileNotFoundError:
            self.advisories.append(
                f"{module}: icon {value!r} matches no file; correct it or drop the key"
            )
        return []

    def _test_manifest_countries_value(self, module, values):
        for value in values:
            if value and len(value) != 2:
                self.advisories.append(
                    f"{module}: {value!r} in `countries` is not a two-letter code"
                )


MANIFEST_FLOOR = 629
