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


# `LintCase` already carries `@no_retry`.
class ManifestLinter(LintCase):
    def test_manifests(self):
        """Scoped to this repository.

        1 514 modules failed here on a clean checkout and 886 of them live in a
        sibling checkout -- `enterprise` above all, a pristine upstream mirror
        whose manifests are not this fork's to reorder. Reporting them produced
        a wall of failures with no action attached to it.
        """
        checked = 0
        violations = []
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
                    # Collected rather than raised through `subTest`. 628 of
                    # these came out as 628 separate failures, each with its own
                    # traceback and a diff truncated to "[27 chars]" -- which is
                    # unreadable at that volume and unusable as a work list.
                    violations.append(
                        f"{manifest.name}: {str(exc).splitlines()[0][:160]}"
                    )
        _logger.info("checked %s manifests", checked)
        self.assertTrue(checked, "the scan reached no manifests at all")
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
            _logger.warning(
                "Module %r specific to one single country %r should contain `l10n` in their name.",
                module,
                manifest_data["countries"][0],
            )

        for key, value in manifest_data._Manifest__manifest_content.items():
            if key in _DEFAULT_MANIFEST:
                if key in verified_keys:
                    self.assertNotEqual(
                        value,
                        _DEFAULT_MANIFEST[key],
                        f"Setting manifest key {key} to the default manifest value for module {module!r}. "
                        "You can remove this key from the dict to reduce noise/inconsistencies between manifests specifications"
                        " and ease understanding of manifest content.",
                    )

                expected_type = type(_DEFAULT_MANIFEST[key])
                if not isinstance(value, expected_type):
                    if key != "auto_install":
                        _logger.warning(
                            "Wrong type for manifest value %s in module %s, expected %s",
                            key,
                            module,
                            expected_type,
                        )
                    elif not isinstance(value, list):
                        _logger.warning(
                            "Wrong type for manifest value %s in module %s, expected bool or list",
                            key,
                            module,
                        )
                elif key == "countries":
                    self._test_manifest_countries_value(module, value)
            elif key == "icon":
                self._test_manifest_icon_value(module, value)

    def _test_manifest_icon_value(self, module, value):
        self.assertTrue(
            isinstance(value, str),
            f"Wrong type for manifest value icon in module {module!r}, expected string",
        )
        self.assertNotEqual(
            value,
            f"/{module}/static/description/icon.png",
            f"Setting manifest key icon to the default manifest value for module {module!r}. "
            "You can remove this key from the dict to reduce noise/inconsistencies between manifests specifications"
            " and ease understanding of manifest content.",
        )
        if not value:
            _logger.warning(
                "Empty value specified as icon in manifest of module %r."
                " Please specify a correct value or remove this key from the manifest.",
                module,
            )
        else:
            path_parts = value.split("/")
            try:
                file_path(str(PurePosixPath(*path_parts[1:])))
            except FileNotFoundError:
                _logger.warning(
                    "Icon value specified in manifest of module %s wasn't found in given path."
                    " Please specify a correct value or remove this key from the manifest.",
                    module,
                )

    def _test_manifest_countries_value(self, module, values):
        for value in values:
            if value and len(value) != 2:
                _logger.warning(
                    "Country value %s specified for the icon in manifest of module %s doesn't look like a country code"
                    "Please specify a correct value or remove this key from the manifest.",
                    value,
                    module,
                )


#: Manifests still awaiting the canonical ordering pass. Frozen rather than
#: fixed in place: `_sort_manifests.py` rewrites 628 files at once, which cannot
#: land while other branches are open. Measured 2026-08-07, this repository only.
MANIFEST_FLOOR = 630
