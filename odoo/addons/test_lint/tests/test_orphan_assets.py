import logging
from pathlib import Path

from odoo.modules import Manifest
from odoo.tests import tagged

from . import lint_case

_logger = logging.getLogger(__name__)

BUNDLED_EXTENSIONS = (".js", ".scss", ".css", ".xml")

URL_FETCHED = frozenset(
    {
        "mail/static/src/discuss/voice_message/worklets/processor.js",
        "mail/static/src/service_worker.js",
        "mail/static/src/worklets/audio_processor.js",
        "web/static/src/module_loader.js",
        "web/static/src/public/database_manager.js",
        "web/static/src/service_worker.js",
    }
)


@tagged("post_install", "-at_install")
class TestOrphanAssets(lint_case.LintCase):
    @staticmethod
    def _declared_paths(manifests, bundle):
        found = set()
        for manifest in manifests:
            for entry in (manifest.get("assets") or {}).get(bundle, ()):
                if isinstance(entry, (list, tuple)):
                    entry = entry[-1] if len(entry) > 1 else entry[0]
                if not isinstance(entry, str) or entry.startswith(
                    ("http://", "https://")
                ):
                    continue
                spec = entry.lstrip("/")
                addon, _, relative = spec.partition("/")
                root = next((Path(m.path) for m in manifests if m.name == addon), None)
                if root is None or not relative:
                    continue
                if any(ch in relative for ch in "*?["):
                    found.update(
                        f"{addon}/{p.relative_to(root).as_posix()}"
                        for p in root.glob(relative)
                        if p.is_file()
                    )
                elif (root / relative).is_file():
                    found.add(spec)
        return found

    def test_static_sources_reach_a_bundle(self):
        with self.superuser_env() as env:
            self._check_static_sources(env)

    def _check_static_sources(self, env):
        IrAsset = env["ir.asset"]
        params = IrAsset._prepare_assets_params()

        installed = set(
            env["ir.module.module"].search([("state", "=", "installed")]).mapped("name")
        )
        manifests = [m for m in Manifest.all_addon_manifests() if m.name in installed]
        bundles = set(self.served_bundle_names(env))
        bundles.update(IrAsset.search([]).mapped("bundle"))

        bundled = set()
        unresolvable = []
        for bundle in sorted(bundles):
            try:
                entries = IrAsset._get_asset_paths(bundle, params)
            except Exception as exc:
                unresolvable.append(f"{bundle}: {exc.__class__.__name__}: {exc}")
                bundled.update(self._declared_paths(manifests, bundle))
                continue
            bundled.update(entry.path.lstrip("/") for entry in entries)

        orphans = []
        checked = 0
        for manifest in manifests:
            source_root = Path(manifest.path) / "static" / "src"
            if not source_root.is_dir():
                continue
            for path in sorted(source_root.rglob("*")):
                if not path.is_file() or path.suffix not in BUNDLED_EXTENSIONS:
                    continue
                relative = (
                    f"{manifest.name}/{path.relative_to(manifest.path).as_posix()}"
                )
                checked += 1
                if relative not in bundled and relative not in URL_FETCHED:
                    orphans.append(relative)

        _logger.info(
            "checked %s static/src file(s) of %s installed module(s) against %s bundle(s)",
            checked,
            len(manifests),
            len(bundles),
        )
        for report in sorted(unresolvable):
            _logger.warning(
                "bundle does not assemble, files taken as declared: %s", report
            )
        self.assertFalse(
            orphans,
            f"{len(orphans)} static/src file(s) belong to no bundle and are "
            f"therefore never served. Declare them, delete them, or -- if the "
            f"browser fetches them by URL -- add them to URL_FETCHED with the "
            f"reason:\n  " + "\n  ".join(sorted(orphans)),
        )

        stale = sorted(
            path
            for path in URL_FETCHED
            if path.split("/", 1)[0] in installed and path in bundled
        )
        self.assertFalse(
            stale,
            f"{len(stale)} URL_FETCHED entr(y/ies) are now bundled, so the "
            f"exemption describes nothing and hides the next real orphan:\n  "
            + "\n  ".join(stale),
        )
