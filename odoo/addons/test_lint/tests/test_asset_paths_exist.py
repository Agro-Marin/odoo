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
