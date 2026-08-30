import pathlib
import re
from unittest.mock import patch

from odoo.exceptions import AccessDenied
from odoo.modules import Manifest
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
class TestDemoDataLoadedCleanly(TransactionCase):
    """`load_demo` catches its own exception, so a broken demo file is a WARNING.

    Nothing then fails: the module is marked `demo = False`, and because
    `ModuleNode.demo_installable` is `all(p.demo for p in self.depends)`, every
    module downstream of it is never even attempted. One bad line in `base`
    turns demo data off for the whole database and says so once, in a log
    nobody reads. That is not hypothetical -- it is how a removed field left in
    `base/demo/res_users_demo.xml` disabled demo everywhere, which in turn made
    every demo-gated test skip instead of fail.
    """

    def _demo_was_asked_for(self):
        """Read the flag, never `base.module_base.demo`.

        That column records the *outcome*: a failed demo load sets it False,
        so guarding on it makes the gate skip in exactly the case it exists to
        catch. Verified by reintroducing the original bug -- both assertions
        skipped, reporting "database built without demo data" about a database
        built with it.
        """
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
        """The exception line, not the last line.

        A ParseError ends by dumping the offending XML, so `splitlines()[-1]`
        reports `</record>` and names neither the file nor the cause.
        """
        lines = [line for line in traceback_text.splitlines() if line.strip()]
        for line in reversed(lines):
            if re.match(r"^\S+(\.\S+)*(Error|Exception|Warning):", line):
                return line
        return lines[-1] if lines else traceback_text

    def test_the_demo_files_a_manifest_promises_all_exist(self):
        """A demo file that is gone raises inside the same swallowed try."""
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
