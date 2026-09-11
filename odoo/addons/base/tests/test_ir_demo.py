import pathlib
import re
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessDenied
from odoo.modules import Manifest, loading
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import config, mute_logger


@tagged("post_install", "-at_install")
class TestIrDemo(TransactionCase):
    def test_install_demo_denies_non_admin(self):
        user = new_test_user(self.env, login="demo_gate_user")
        demo = self.env["ir.demo"].with_user(user)
        with (
            patch("odoo.modules.loading.force_demo") as force_demo,
            mute_logger("odoo.addons.base.models.ir_module"),
        ):
            with self.assertRaises(AccessDenied):
                demo.install_demo()
            force_demo.assert_not_called()

    def test_install_demo_admin_gated_path(self):
        with patch("odoo.modules.loading.force_demo") as force_demo:
            action = self.env["ir.demo"].install_demo()
            force_demo.assert_called_once()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["url"], "/odoo")
        self.assertEqual(action["target"], "self")


@tagged("post_install", "-at_install")
class TestIrDemoFailure(TransactionCase):
    def test_error_field_stores_multiline_traceback(self):
        module = self.env["ir.module.module"].search([], limit=1)
        multiline = "Traceback (most recent call last):\n  File ...\nValueError: boom"
        failure = self.env["ir.demo_failure"].create(
            {"module_id": module.id, "error": multiline}
        )
        self.assertEqual(failure.error, multiline)
        self.assertEqual(failure._fields["error"].type, "text")

    def test_wizard_aggregates_orphan_failures(self):
        modules = self.env["ir.module.module"].search([], limit=3)
        self.assertTrue(modules, "Expected at least one installed module to reference")
        Failure = self.env["ir.demo_failure"]
        failures = Failure.browse()
        for module in modules:
            failures |= Failure.create({"module_id": module.id, "error": "boom"})

        orphans = Failure.search([("wizard_id", "=", False)])
        self.assertTrue(
            failures <= orphans, "Newly created failures must be orphan rows"
        )
        wizard = self.env["ir.demo_failure.wizard"].create(
            {"failure_ids": [(6, 0, orphans.ids)]}
        )

        self.assertEqual(wizard.failures_count, len(orphans))
        self.assertEqual(wizard.failure_ids, orphans)
        self.assertTrue(failures <= wizard.failure_ids)


@tagged("post_install", "-at_install")
class TestDemoFailure(TransactionCase):
    @mute_logger("odoo.modules.loading")
    def test_a_failed_demo_leaves_no_pending_write_behind(self):
        partner = self.env["res.partner"].create({"name": "Outlives the demo"})
        self.env.flush_all()

        def load_data_then_fail(env, idref, mode, kind, package):
            company = env["res.partner"].create(
                {"name": "Created by a failing demo", "is_company": True}
            )
            env["res.partner"].browse(partner.id).parent_id = company
            raise ValueError("the demo file is broken")

        package = SimpleNamespace(
            name="base",
            id=self.env.ref("base.module_base").id,
            manifest={"demo": ["broken.xml"]},
        )
        with patch.object(loading, "load_data", load_data_then_fail):
            self.assertFalse(loading.load_demo(self.env, package, {}, "init"))

        self.env.flush_all()
        self.assertFalse(partner.parent_id)


@tagged("post_install", "-at_install")
class TestDemoDataLoadedCleanly(TransactionCase):
    def _demo_was_asked_for(self):
        return bool(config["with_demo"])

    def test_no_module_was_quietly_left_without_its_demo_data(self):
        if not self._demo_was_asked_for():
            self.skipTest("run without --with-demo")

        stranded = self.env["ir.module.module"].search(
            [("state", "=", "installed"), ("demo", "=", False)]
        )

        self.assertFalse(
            stranded.mapped("name"),
            "installed with demo data, yet these modules have none. The first "
            "one to fail is the cause; the rest are its dependents, which are "
            "never attempted. Search the install log for "
            "'demo data failed to install' to see the traceback load_demo "
            "swallowed.",
        )

    def test_nothing_recorded_a_demo_failure(self):
        if not self._demo_was_asked_for():
            self.skipTest("run without --with-demo")

        failures = self.env["ir.demo_failure"].search([])

        self.assertFalse(
            [f"{f.module_id.name}: {self._blame(f.error)}" for f in failures],
            "load_demo recorded these while installing this database",
        )

    @staticmethod
    def _blame(traceback_text):
        lines = [line for line in traceback_text.splitlines() if line.strip()]
        for line in reversed(lines):
            if re.match(r"^\S+(\.\S+)*(Error|Exception|Warning):", line):
                return line
        return lines[-1] if lines else traceback_text

    def test_the_demo_files_a_manifest_promises_all_exist(self):
        missing = []
        for module in self.env["ir.module.module"].search(
            [("state", "=", "installed")]
        ):
            manifest = Manifest.for_addon(module.name, display_warning=False)
            if manifest is None:
                continue
            missing.extend(
                f"{module.name}: {relative}"
                for relative in manifest.get("demo", [])
                if not (pathlib.Path(manifest.path) / relative).exists()
            )

        self.assertFalse(missing, "manifests promise demo files that do not exist")
