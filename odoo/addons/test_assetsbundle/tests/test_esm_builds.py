import contextlib
import importlib.util
import uuid
from datetime import timedelta
from unittest.mock import patch

from psycopg.errors import SerializationFailure, UniqueViolation

from odoo import fields
from odoo.api import SUPERUSER_ID
from odoo.db import db_connect
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_path, mute_logger
from odoo.tools.assets import esm_index
from odoo.tools.assets.esbuild import EsbuildResult

from odoo.addons.base.models import ir_qweb_assets
from odoo.addons.base.models.assetsbundle import AssetsBundle


@tagged("post_install", "-at_install", "assets_bundle")
class TestEsmBuildLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Build = cls.env["ir.asset.build"].sudo()

    def _row(self, directory, name="b.esm.js"):
        IrAttachment = self.env["ir.attachment"].with_user(SUPERUSER_ID)
        return IrAttachment.create(
            IrAttachment._prepare_generated_asset_vals(
                name=name,
                mimetype="text/javascript",
                raw=b"export {};",
                url=f"{directory}{name}",
            )
        )

    def _publish(self, directory, variant="default", bundle="test.builds", **extra):
        return self.Build._publish(
            {
                "kind": "bundle",
                "bundle": bundle,
                "variant": variant,
                "directories": [directory],
                **extra,
            }
        )

    def _age(self, build, days):
        build.superseded_at = fields.Datetime.now() - timedelta(days=days)

    def test_a_variant_never_supersedes_another(self):
        plain = self._publish("/web/assets/esm/aaaa/")
        paged = self._publish("/web/assets/esm/bbbb/", variant="page=web.assets_web")
        self.assertEqual((plain | paged).mapped("state"), ["current", "current"])

    def test_a_rebuild_supersedes_and_keeps_the_previous_build_served(self):
        row = self._row("/web/assets/esm/aaaa/")
        first = self._publish("/web/assets/esm/aaaa/")
        second = self._publish("/web/assets/esm/bbbb/")
        self.assertEqual(first.state, "superseded")
        self.assertTrue(first.superseded_at)
        self.assertEqual(second.state, "current")
        self.assertTrue(row.exists(), "a page rendered a minute ago still asks for it")

    def test_a_revert_recurrents_the_earlier_build(self):
        first = self._publish("/web/assets/esm/aaaa/")
        second = self._publish("/web/assets/esm/bbbb/")
        again = self._publish("/web/assets/esm/aaaa/")
        self.assertEqual(again, first)
        self.assertEqual(first.state, "current")
        self.assertFalse(first.superseded_at)
        self.assertEqual(second.state, "superseded")

    def test_the_sweep_waits_for_the_grace(self):
        kept_row = self._row("/web/assets/esm/aaaa/")
        old = self._publish("/web/assets/esm/aaaa/")
        self._publish("/web/assets/esm/bbbb/")
        self._age(old, 1)
        self.Build._sweep()
        self.assertTrue(old.exists())
        self.assertTrue(kept_row.exists())
        self._age(old, 30)
        self.Build._sweep()
        self.assertFalse(old.exists())
        self.assertFalse(kept_row.exists())

    def test_the_sweep_keeps_a_directory_another_build_still_owns(self):
        shared = self._row("/web/assets/esm/cccc/")
        old = self._publish("/web/assets/esm/cccc/")
        self._publish("/web/assets/esm/dddd/")
        self._publish("/web/assets/esm/cccc/", variant="page=web.assets_frontend")
        self._age(old, 30)
        self.Build._sweep()
        self.assertFalse(old.exists())
        self.assertTrue(shared.exists(), "the page variant compiled the same bytes")

    def test_one_current_build_per_variant_is_a_constraint(self):
        self._publish("/web/assets/esm/aaaa/")
        with (
            mute_logger("odoo.db.cursor"),
            self.assertRaises(UniqueViolation),
            self.env.cr.savepoint(),
        ):
            self.Build.create(
                {
                    "kind": "bundle",
                    "bundle": "test.builds",
                    "variant": "default",
                    "directories": ["/web/assets/esm/eeee/"],
                    "fingerprint": "eeee",
                }
            )

    def test_reuse_prefers_the_current_build_then_one_in_grace(self):
        old = self._publish("/web/assets/esm/aaaa/", source_key="k1")
        current = self._publish("/web/assets/esm/bbbb/", source_key="k2")
        self.assertEqual(
            self.Build._find_reusable("bundle", "test.builds", "default", "k2"),
            current,
        )
        self.assertEqual(
            self.Build._find_reusable("bundle", "test.builds", "default", "k1"), old
        )
        self.assertFalse(
            self.Build._find_reusable("bundle", "test.builds", "page=x", "k2")
        )

    def test_a_bundle_no_installed_addon_declares_is_retired(self):
        gone = self._publish(
            "/web/assets/esm/ffff/", bundle="test_builds_not_an_addon.assets"
        )
        kept = self._publish("/web/assets/esm/abab/", bundle="web.assets_web")
        self.Build._retire_uninstalled()
        self.assertEqual(gone.state, "superseded")
        self.assertEqual(kept.state, "current")

    def test_an_unchanged_publish_writes_nothing(self):
        build = self._publish("/web/assets/esm/aaaa/", source_key="k")
        Model = type(self.Build)
        refuse = AssertionError("an unchanged publish must not write")
        with (
            patch.object(Model, "write", side_effect=refuse),
            patch.object(Model, "create", side_effect=refuse),
        ):
            again = self._publish("/web/assets/esm/aaaa/", source_key="k")
        self.assertEqual(again, build)


@tagged("post_install", "-at_install", "assets_bundle")
class TestEsmBuildVariantsAreServedSideBySide(TransactionCase):
    def test_two_variants_of_one_bundle_both_stay_served(self):
        qweb = self.env["ir.qweb"]
        # the production branch writes rows and the build on this cursor
        with patch.object(ir_qweb_assets._module, "current_test", None):
            plain = qweb._save_esm_attachment("test.builds.side", "export const a=1;")
            paged = qweb._save_esm_attachment(
                "test.builds.side",
                "export const a=2;",
                variant="page=web.assets_frontend",
            )
            plain_again = qweb._save_esm_attachment(
                "test.builds.side", "export const a=1;"
            )
        self.assertEqual(plain_again, plain)
        IrAttachment = self.env["ir.attachment"].sudo()
        for url in (plain, paged):
            with self.subTest(url=url):
                self.assertTrue(
                    IrAttachment.search_count(
                        IrAttachment._get_domain_generated_assets(url)
                    )
                )
        builds = (
            self.env["ir.asset.build"]
            .sudo()
            .search([("bundle", "=", "test.builds.side")])
        )
        self.assertEqual(builds.mapped("state"), ["current", "current"])


@tagged("post_install", "-at_install", "assets_bundle")
class TestEsmBuildAdoption(TransactionCase):
    def _migration(self):
        path = file_path("base/migrations/1.98/post-migrate_esm_asset_builds.py")
        spec = importlib.util.spec_from_file_location("esm_asset_builds", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _row(self, url):
        IrAttachment = self.env["ir.attachment"].with_user(SUPERUSER_ID)
        return IrAttachment.create(
            IrAttachment._prepare_generated_asset_vals(
                name=url.rsplit("/", 1)[-1],
                mimetype="text/javascript",
                raw=b"export {};",
                url=url,
            )
        )

    def test_every_stored_directory_becomes_one_superseded_build(self):
        Build = self.env["ir.asset.build"].sudo()
        self._row("/web/assets/esm/zzad01/x.adopt.esm.js")
        self._row("/web/assets/esm/zzad01/x.adopt.meta.json")
        self._row("/web/assets/esm/zzad02/chunk-ABCDEFGH.esm.js")
        self._row("/web/assets/esm/zzad02/group.meta.json")
        self._row("/web/assets/lib/zzad03/web/static/lib/x.js")
        bridge = self._row("/web/assets/esm/bridges/zzad04.js")
        pointer = self._row("/web/assets/esm/by-source/k/x.adopt.json")
        self._row("/web/assets/esm/zzad05/x.owned.esm.js")
        owned = Build._publish(
            {
                "kind": "bundle",
                "bundle": "x.owned",
                "variant": "default",
                "directories": ["/web/assets/esm/zzad05/"],
            }
        )

        self._migration().migrate(self.env.cr, "1.96")

        adopted = Build.search([("variant", "=like", "legacy:%")]).filtered(
            lambda b: b.directories[0].split("/")[4].startswith("zzad")
        )
        self.assertEqual(
            {(b.kind, b.bundle, b.directories[0]) for b in adopted},
            {
                ("bundle", "x.adopt", "/web/assets/esm/zzad01/"),
                ("group", "legacy", "/web/assets/esm/zzad02/"),
                ("lib", "esm.libs", "/web/assets/lib/zzad03/"),
            },
        )
        self.assertEqual(set(adopted.mapped("state")), {"superseded"})
        self.assertEqual(owned.state, "current", "an owned directory is left alone")
        self.assertTrue(bridge.exists(), "a bridge belongs to no build")
        self.assertFalse(pointer.exists(), "the build carries the source key now")


@tagged("post_install", "-at_install", "assets_bundle")
class TestEsmBuildRobustness(TransactionCase):
    def test_the_publication_lock_works_on_a_cursor_already_in_a_transaction(self):
        # a test cursor serving an HTTP test shares the test's transaction; the
        # lock must not ask it to change its isolation
        self.env.cr.execute("SELECT 1")
        self.env["ir.qweb"]._lock_esm_publication(self.env.cr)

    def test_a_group_is_named_by_its_code_not_its_metafile(self):
        qweb = self.env["ir.qweb"]
        code = {"g6.child.esm.js": b"export const x = 1;"}
        with patch.object(ir_qweb_assets._module, "current_test", None):
            first = qweb._save_esm_group(
                "runtime:g6.parent",
                {**code, "group.meta.json": b'{"tmp": "/tmp/odoo-esbuild-aaaa"}'},
                ["g6.child"],
                variant="default",
                source_key="g6",
            )
            second = qweb._save_esm_group(
                "runtime:g6.parent",
                {**code, "group.meta.json": b'{"tmp": "/tmp/odoo-esbuild-bbbb"}'},
                ["g6.child"],
                variant="default",
                source_key="g6",
            )
        self.assertEqual(first, second)

    def test_a_publication_race_that_cannot_settle_does_not_raise(self):
        Build = self.env["ir.asset.build"].sudo()
        with patch.object(
            type(Build), "_publish_once", side_effect=SerializationFailure("raced")
        ):
            published = Build._publish(
                {
                    "kind": "bundle",
                    "bundle": "test.builds.race",
                    "variant": "default",
                    "directories": ["/web/assets/esm/rrrr/"],
                }
            )
        self.assertFalse(published)

    def test_a_readonly_cursor_defers_a_build_whose_rows_are_served(self):
        qweb = self.env["ir.qweb"]
        build = {
            "kind": "bundle",
            "bundle": "test.builds.readonly",
            "variant": "default",
            "directories": ["/web/assets/esm/ssss/"],
        }
        with (
            patch.object(ir_qweb_assets._module, "current_test", None),
            patch.object(self.env.cr, "_readonly", True),
        ):
            qweb._save_esm_attachment_rows(
                [], bundle="test.builds.readonly", build=build
            )

    def test_a_supersession_invalidates_every_worker_s_assets_cache(self):
        Build = self.env["ir.asset.build"].sudo()
        spec = {"kind": "bundle", "bundle": "test.builds.inval", "variant": "default"}
        Build._publish({**spec, "directories": ["/web/assets/esm/tttt/"]})
        with patch.object(type(self.env.registry), "clear_cache") as clear_cache:
            Build._publish({**spec, "directories": ["/web/assets/esm/uuuu/"]})
        clear_cache.assert_any_call("assets")


@tagged("post_install", "-at_install", "assets_bundle")
class TestEsbuildLockSerializesCompiles(TransactionCase):
    registry_test_mode = False
    BUNDLE = "test.builds.lock"

    def setUp(self):
        super().setUp()
        self.key = f"lock-{uuid.uuid4().hex}"
        self.variant = esm_index.variant_key({})
        self.compiles = []
        self.qweb = self.env["ir.qweb"]
        self.env.cr.execute("SELECT 1")
        self.addCleanup(self._forget_committed_build)

    def _forget_committed_build(self):
        with db_connect(self.env.cr.dbname).cursor() as cr:
            cr.execute(
                "DELETE FROM ir_asset_build WHERE source_key = %s RETURNING directories",
                (self.key,),
            )
            directories = [d for (dirs,) in cr.fetchall() for d in dirs]
            if directories:
                cr.execute(
                    "DELETE FROM ir_attachment WHERE url LIKE ANY(%s)",
                    ([f"{d}%" for d in directories],),
                )

    def _committed_build(self):
        with db_connect(self.env.cr.dbname).cursor() as cr:
            cr.execute(
                "SELECT count(*) FROM ir_asset_build WHERE source_key = %s",
                (self.key,),
            )
            return cr.fetchone()[0]

    @contextlib.contextmanager
    def _own_lock_cursor(self, _bundle, on_release=None):
        with db_connect(self.env.cr.dbname).cursor() as lock_cr:
            try:
                yield lock_cr
                if on_release:
                    on_release()
            finally:
                lock_cr.rollback()

    def _compile(self, on_release=None):
        def compile_bundle(*_args, **_kwargs):
            self.compiles.append(1)
            return EsbuildResult(f"export const k = {self.key!r};", None, None)

        Qweb = type(self.qweb)
        with (
            patch.object(
                Qweb,
                "_get_esbuild_lock_cursor",
                lambda _self, bundle: self._own_lock_cursor(bundle, on_release),
            ),
            patch.object(Qweb, "_get_dynamic_child_bundles", lambda *_a, **_k: []),
            patch.object(
                Qweb, "_get_esbuild_child_externals", lambda *_a, **_k: (None, {})
            ),
            patch.object(Qweb, "_get_exported_specs", lambda *_a, **_k: frozenset()),
            patch.object(Qweb, "_esm_source_key", lambda *_a, **_k: self.key),
            patch.object(AssetsBundle, "esbuild_native_bundle", compile_bundle),
            # outside a test the build is published through its own cursor,
            # the way a request escalates, and read back through the lock's
            patch.object(ir_qweb_assets._module, "current_test", None),
            patch.object(ir_qweb_assets, "request", object()),
        ):
            return self.qweb._compile_with_esbuild_locked(
                self.BUNDLE, AssetsBundle(self.BUNDLE, [], env=self.env), {}
            )

    def test_the_waiter_reuses_a_build_committed_after_its_snapshot(self):
        self.qweb._save_esm_attachment(
            self.BUNDLE,
            "export const k = 'other';",
            source_key=self.key,
            variant=self.variant,
        )
        self.assertFalse(
            self.env["ir.asset.build"]
            .sudo()
            ._find_reusable("bundle", self.BUNDLE, self.variant, self.key),
            "the test transaction cannot see the committed build",
        )
        result, _children = self._compile()
        self.assertEqual(self.compiles, [], "the lock holder's build is reused")
        self.assertTrue(result.prebuilt)
        self.assertIn("'other'", result.code)

    def test_the_holder_publishes_before_it_releases_the_lock(self):
        seen_at_release = []
        result, _children = self._compile(
            on_release=lambda: seen_at_release.append(self._committed_build())
        )
        self.assertEqual(len(self.compiles), 1)
        self.assertEqual(result.source_key, self.key)
        self.assertEqual(seen_at_release, [1])


@tagged("post_install", "-at_install", "assets_bundle")
class TestEsmRowsWrittenOnTheCallersTransaction(TransactionCase):
    def test_the_nodes_naming_them_do_not_outlive_a_rollback(self):
        qweb = self.env["ir.qweb"]
        IrAttachment = self.env["ir.attachment"]
        vals = IrAttachment._prepare_generated_asset_vals(
            name="test.builds.rollback.esm.js",
            mimetype="text/javascript",
            raw=b"export {};",
            url=f"/web/assets/esm/{uuid.uuid4().hex[:16]}/test.builds.rollback.esm.js",
        )
        computed = []
        original = AssetsBundle.get_native_module_data

        def counted(bundle):
            computed.append(bundle.name)
            return original(bundle)

        self.env.registry.clear_cache("assets")
        with (
            patch.object(ir_qweb_assets._module, "current_test", None),
            patch.object(AssetsBundle, "get_native_module_data", counted),
        ):
            savepoint = self.env.cr.savepoint()
            qweb._save_esm_attachment_rows([vals], bundle="test.builds.rollback")
            qweb._get_native_module_data_cached("test_assetsbundle.native_esm", {})
            savepoint.close(rollback=True)
            self.assertFalse(IrAttachment.search_count([("url", "=", vals["url"])]))
            qweb._get_native_module_data_cached("test_assetsbundle.native_esm", {})
        self.assertEqual(len(computed), 2, "what was cached over the rows is dropped")
