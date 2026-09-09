import collections
import io
import pathlib
import zipfile

from odoo.modules.module import Manifest
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestHandlerShipping(HttpCase):
    """``/iot/get_handlers`` decides which driver files reach a box.

    Which module ships a driver is a manifest property since the driver split,
    so these pin the two keys rather than a list of module names.
    """

    def _box(self, version="L25.07", auto_update=True):
        return (
            self.env["iot.box"]
            .sudo()
            .create(
                {
                    "name": "Handler Box",
                    "identifier": "handler-box",
                    "ip": "10.0.0.4",
                    "version": version,
                    "drivers_auto_update": auto_update,
                }
            )
        )

    def _fetch(self, identifier="handler-box", auto="False"):
        return self.url_open(f"/iot/get_handlers?identifier={identifier}&auto={auto}")

    def _names(self, response):
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            return set(zf.namelist())

    def test_the_box_firmware_handlers_always_ship(self):
        self._box()
        names = self._names(self._fetch())
        self.assertIn("drivers/printer_driver_base.py", names)
        self.assertIn("interfaces/serial_interface.py", names)

    def test_a_driver_marked_always_ships_while_uninstalled(self):
        """``iot_handlers_always`` replaced a hardcoded module name in this
        controller. The box has to be able to report a fiscal data module
        before anyone installs the app that acts on one."""
        self.assertNotEqual(
            self.env["ir.module.module"]
            .sudo()
            .search([("name", "=", "iot_blackbox_be")], limit=1)
            .state,
            "installed",
            "this test is about a module that is NOT installed",
        )
        self._box()
        self.assertIn("drivers/serial_blackbox_driver.py", self._names(self._fetch()))

    def test_an_uninstalled_driver_without_that_key_does_not_ship(self):
        self._box()
        self.assertNotIn("drivers/adam_scale_driver.py", self._names(self._fetch()))

    def test_a_dated_image_is_not_sent_what_it_already_carries(self):
        """A dated box builds its handlers from git. Re-sending them would
        overwrite the git copy with the database's."""
        self._box(version="2025.09.01")
        names = self._names(self._fetch())
        self.assertNotIn("drivers/serial_blackbox_driver.py", names)
        self.assertNotIn("drivers/IngenicoDriver.py", names)

    def test_a_windows_box_is_not_sent_linux_handlers(self):
        self._box(version="W25.07")
        names = self._names(self._fetch())
        self.assertFalse(
            [n for n in names if n.endswith("_L.py")],
            "a Windows box must not receive Linux-only handlers",
        )

    def test_a_linux_box_is_not_sent_windows_handlers(self):
        self._box(version="L25.07")
        names = self._names(self._fetch())
        self.assertFalse([n for n in names if n.endswith("_W.py")])

    def test_an_unknown_box_gets_nothing(self):
        self.assertEqual(self._fetch(identifier="no-such-box").status_code, 401)

    def test_auto_update_off_refuses_an_automatic_request(self):
        self._box(auto_update=False)
        self.assertEqual(self._fetch(auto="True").status_code, 401)
        self.assertEqual(
            self._fetch(auto="False").status_code,
            200,
            "a hand-triggered update is still allowed",
        )


@tagged("post_install", "-at_install")
class TestHandlerNamespace(HttpCase):
    def test_no_two_modules_claim_the_same_handler_path(self):
        """Handlers land flat on the box, so the path inside the zip is the
        whole namespace.

        Before the driver split one module owned the payment terminals and a
        clash was local to it. Nine modules contribute now, ``zipfile`` accepts
        a duplicate name without complaint, and extraction keeps whichever was
        written last -- so a collision would be decided by module ordering and
        report nothing. This is the model-name-ownership question one layer
        down.
        """
        owners = collections.defaultdict(list)
        for manifest in Manifest.all_addon_manifests():
            handlers = pathlib.Path(manifest.path) / "iot_handlers"
            if not handlers.is_dir():
                continue
            for handler in handlers.glob("*/*"):
                if handler.name.startswith((".", "_")):
                    continue
                owners[f"{handler.parent.name}/{handler.name}"].append(manifest.name)

        self.assertTrue(owners, "the scan reached no handlers at all")
        clashes = {path: mods for path, mods in owners.items() if len(mods) > 1}
        self.assertFalse(
            clashes,
            "these handler paths are claimed by more than one module, and the "
            "box would silently keep one of them: %s" % clashes,
        )
