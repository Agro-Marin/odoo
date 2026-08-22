import logging
from pathlib import Path

import odoo
from odoo import SUPERUSER_ID, api
from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)

SETUP_SUFFIX = "_setup"
TEST_SUFFIX = ".test.js"


@tagged("post_install", "-at_install")
class TestSetupBundleHasNoTests(lint_case.LintCase):

    def test_setup_bundles_carry_no_test_files(self):
        offenders = []
        checked = 0
        skipped = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            for bundle in self.served_bundle_names(env):
                if not bundle.endswith(SETUP_SUFFIX):
                    continue
                try:
                    files = env["ir.qweb"]._get_asset_bundle(bundle, js=True).files
                except Exception as exc:
                    skipped.append(f"{bundle} ({type(exc).__name__})")
                    continue
                checked += 1
                offenders.extend(
                    f"{bundle}: {url}"
                    for url in ((f["url"] or "").lstrip("/") for f in files)
                    if url.endswith(TEST_SUFFIX)
                )

        _logger.info("checked %s setup bundle(s)", checked)
        self.assertFalse(
            skipped,
            f"{len(skipped)} setup bundle(s) did not assemble, so this check "
            f"passed on silence rather than on evidence: {', '.join(skipped)}",
        )
        self.assertTrue(
            checked,
            "no *_setup bundle was checked — the naming convention this gate "
            "keys on has moved, and the gate is now vacuous",
        )
        self.assertFalse(
            offenders,
            "test file(s) in a setup bundle, which is evaluated without the "
            "per-file suite that `describe.current` needs; the page will die "
            "before HOOT starts and report no tests at all:\n  "
            + "\n  ".join(sorted(offenders)),
        )

    def test_setup_bundle_globs_reach_no_test_file(self):
        """The same question asked of the manifests, not of the registry.

        `served_bundle_names` skips a manifest whose module is not installed,
        and this suite's CI lane installs `test_lint` alone -- so the check
        above has never actually looked at, say,
        `im_livechat.embed_assets_unit_tests_setup`, the very bundle it was
        written for.  Three `.test.js` files were moved into a helper directory
        that bundle globs, months after being moved out of it, and nothing
        noticed.

        This one reads the manifests on disk, so it covers every addon on the
        path whether installed or not.  It resolves plain globs and honours
        ``('remove', ...)``; it cannot follow ``('include', <bundle>)``, which
        is exactly what the registry-based check above covers when the module
        is installed.  The two are complementary; neither is total alone.
        """
        roots = [Path(p) for p in odoo.addons.__path__]
        roots = [p for p in roots if p.is_dir()]

        def resolve(pattern: str) -> set[Path]:
            hits: set[Path] = set()
            for root in roots:
                hits.update(root.glob(pattern))
            return hits

        offenders = []
        checked = 0
        for manifest in Manifest.all_addon_manifests():
            for bundle, entries in (manifest.get("assets") or {}).items():
                if not bundle.endswith(SETUP_SUFFIX):
                    continue
                checked += 1
                files: set[Path] = set()
                for entry in entries:
                    if isinstance(entry, str):
                        files |= resolve(entry)
                        continue
                    if not isinstance(entry, (list, tuple)) or not entry:
                        continue
                    directive, *rest = entry
                    if directive == "include" or not rest:
                        continue
                    if directive == "remove":
                        files -= resolve(rest[0])
                    else:
                        files |= resolve(rest[-1])
                offenders.extend(
                    f"{bundle}: {path.name}"
                    for path in files
                    if path.name.endswith(TEST_SUFFIX)
                )

        _logger.info("scanned %s declared setup bundle(s)", checked)
        self.assertTrue(
            checked,
            "no *_setup bundle was found in any manifest -- the naming "
            "convention this gate keys on has moved, and the scan is vacuous",
        )
        self.assertFalse(
            sorted(set(offenders)),
            "a setup bundle's own globs reach a test file. A setup bundle is "
            "evaluated as plain modules, with no per-file suite for "
            "`describe.current`, so the page dies before HOOT starts and "
            "reports no tests at all. Move the file out of the helper "
            "directory the glob covers:\n  "
            + "\n  ".join(sorted(set(offenders))),
        )
