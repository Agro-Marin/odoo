import logging
from pathlib import Path

from odoo import SUPERUSER_ID, api
from odoo.modules import Manifest
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case
from odoo.addons.base.models.ir_asset_paths import (
    INCLUDE_DIRECTIVE,
    REMOVE_DIRECTIVE,
)

_logger = logging.getLogger(__name__)

GLOB_CHARS = "*?["


@tagged("post_install", "-at_install")
class TestAssetPathsExist(lint_case.LintCase):
    def test_manifest_asset_paths_match_a_file(self):
        """Every path a manifest's ``assets`` names must match something on disk.

        A path that matches nothing is not inert. ``remove`` raises
        ``AssetDirectiveError`` when its target is absent, and that happens
        while *assembling the bundle*, so the failure is not scoped to the
        module that owns the manifest: any database with it installed aborts on
        startup under ``--test-enable``, taking the whole run with it.

        This is the failure mode of deleting a file that a manifest still
        mentions, which is easy to miss because the deletion looks safe --
        nothing imports the file, and greping for importers finds nothing. The
        reference lives in Python, not in JS. (Written after doing exactly that
        to ``pos_settle_due``.)

        Non-``remove`` directives are checked too: a glob matching nothing is
        dead weight that silently ships no asset, which is how a stylesheet or
        a script goes missing without anything failing.

        Paths into an addon that is not on this addons_path are skipped -- the
        bundle can only ever contain modules it can see.
        """
        manifests = list(Manifest.all_addon_manifests())
        addon_dirs = {m.name: Path(m.path) for m in manifests}
        attachment_urls = set()
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            attachment_urls.update(
                (row["url"] or "").lstrip("/")
                for row in env["ir.attachment"].search_read(
                    [("url", "!=", False)], ["url"]
                )
            )
        missing = []
        checked = 0

        def check(module, bundle, spec, directive):
            nonlocal checked
            if not isinstance(spec, str) or spec.startswith(("http://", "https://")):
                return
            addon, _, relative = spec.partition("/")
            root = addon_dirs.get(addon)
            if root is None or not relative:
                return
            checked += 1
            if any(ch in relative for ch in GLOB_CHARS):
                try:
                    if next(root.glob(relative), None) is not None:
                        return
                except ValueError, OSError:
                    return
            elif (root / relative).exists():
                return
            if spec.lstrip("/") in attachment_urls:
                return
            missing.append(
                f"{module}: {bundle}: "
                f"{directive + ' ' if directive else ''}{spec!r} matches no file"
            )

        for manifest in manifests:
            if manifest.name == "test_assetsbundle":
                continue
            for bundle, entries in (manifest.get("assets") or {}).items():
                for entry in entries:
                    if isinstance(entry, str):
                        check(manifest.name, bundle, entry, None)
                        continue
                    if not isinstance(entry, (list, tuple)) or not entry:
                        continue
                    directive = entry[0]
                    if directive == INCLUDE_DIRECTIVE:
                        continue
                    for operand in entry[1:]:
                        check(manifest.name, bundle, operand, directive)

        _logger.info("checked %s manifest asset paths", checked)
        self.assertFalse(
            missing,
            f"{len(missing)} manifest asset path(s) match no file. A `remove` "
            f"whose target is gone aborts every database that installs the "
            f"module:\n  " + "\n  ".join(sorted(missing)),
        )

        self.assertEqual(REMOVE_DIRECTIVE, "remove")
