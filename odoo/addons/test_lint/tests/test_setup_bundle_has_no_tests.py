import logging
from pathlib import Path

import odoo
from odoo.modules import Manifest
from odoo.tests import tagged

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
        with self.superuser_env() as env:
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
            "directory the glob covers:\n  " + "\n  ".join(sorted(set(offenders))),
        )
