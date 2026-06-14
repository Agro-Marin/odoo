"""Tests for ``IrAttachment._gc_esm_assets`` (deferred ESM artifact GC).

Bundle rebuilds defer stale-version deletion to this autovacuum; bridges
have no other GC path at all. The matrix below pins the sweep criteria:
newest-per-name always survives, the grace window is honored and
configurable, bridges are age-swept, classic bundles are untouched.
"""

from odoo.api import SUPERUSER_ID
from odoo.tests.common import TransactionCase


class TestEsmAssetGc(TransactionCase):
    def _mk(self, name: str, url: str, days_old: int = 0):
        """Create a public asset attachment, optionally backdated."""
        att = (
            self.env["ir.attachment"]
            .with_user(SUPERUSER_ID)
            .create(
                {
                    "name": name,
                    "url": url,
                    "type": "binary",
                    "public": True,
                    "res_model": "ir.ui.view",
                    "res_id": False,
                    "raw": b"/* gc probe */",
                    "mimetype": "text/javascript",
                }
            )
        )
        if days_old:
            self.env.cr.execute(
                "UPDATE ir_attachment"
                " SET write_date = write_date - %s::interval,"
                "     create_date = create_date - %s::interval"
                " WHERE id = %s",
                [f"{days_old} days", f"{days_old} days", att.id],
            )
            att.invalidate_recordset()
        return att

    def test_gc_matrix(self):
        """Superseded old rows go; live, recent, and classic rows stay."""
        # Superseded version + sidecar, both past the grace window.
        old_v1 = self._mk("x.gcb.esm.js", "/web/assets/esm/aaaa/x.gcb.esm.js", 30)
        old_map = self._mk(
            "x.gcb.esm.js.map", "/web/assets/esm/aaaa/x.gcb.esm.js.map", 30
        )
        # Current version (newest per name) — survives. Rebuilds create the
        # sidecar under the same NAME as the old one (only the hash dir in
        # the URL changes), which is what supersedes old_map above.
        new_v2 = self._mk("x.gcb.esm.js", "/web/assets/esm/bbbb/x.gcb.esm.js")
        new_map = self._mk("x.gcb.esm.js.map", "/web/assets/esm/bbbb/x.gcb.esm.js.map")
        # Stable bundle: its ONLY row is ancient but is the newest per
        # name — must survive regardless of age.
        lone_old = self._mk("y.gcb.esm.js", "/web/assets/esm/cccc/y.gcb.esm.js", 400)
        # Superseded but still within the grace window — survives this run.
        recent_old = self._mk("z.gcb.esm.js", "/web/assets/esm/dddd/z.gcb.esm.js", 2)
        recent_new = self._mk("z.gcb.esm.js", "/web/assets/esm/eeee/z.gcb.esm.js")
        # Bridges: age is the only criterion.
        bridge_old = self._mk(
            "aabbccddeeff0011.js", "/web/assets/esm/bridges/aabbccddeeff0011.js", 30
        )
        bridge_new = self._mk(
            "1100ffeeddccbbaa.js", "/web/assets/esm/bridges/1100ffeeddccbbaa.js", 1
        )
        # Classic concatenated bundle: name matches no ESM suffix — never
        # touched by this vacuum even when ancient.
        classic = self._mk(
            "x.gcb.min.js", "/web/assets/0123456/x.gcb.min.js", 400
        )

        self.env["ir.attachment"]._gc_esm_assets()

        self.assertFalse(old_v1.exists(), "superseded old version must be GC'd")
        self.assertFalse(old_map.exists(), "superseded old sidecar must be GC'd")
        self.assertFalse(bridge_old.exists(), "aged bridge shim must be GC'd")
        self.assertTrue(new_v2.exists(), "current version must survive")
        self.assertTrue(new_map.exists(), "current sidecar must survive")
        self.assertTrue(lone_old.exists(), "newest-per-name survives any age")
        self.assertTrue(recent_old.exists(), "within grace window — survives")
        self.assertTrue(recent_new.exists())
        self.assertTrue(bridge_new.exists(), "young bridge survives")
        self.assertTrue(classic.exists(), "classic bundles are out of scope")

    def test_gc_grace_window_configurable(self):
        """``web.esm.gc_grace_days`` widens the window."""
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esm.gc_grace_days", "60"
        )
        bridge = self._mk(
            "22334455667788aa.js", "/web/assets/esm/bridges/22334455667788aa.js", 30
        )
        self.env["ir.attachment"]._gc_esm_assets()
        self.assertTrue(
            bridge.exists(), "30-day-old bridge survives a 60-day grace window"
        )

    def test_gc_phantom_non_superuser_row(self):
        """A serving-group user's same-named row must not pose as 'newest'.

        The live (newest-per-name) computation is filtered to superuser-created
        rows. Without that, a higher-id row created by a website designer (who
        passes ``_check_serving_attachments``) would become the phantom 'newest'
        and mark the genuine stable bundle stale — deleting a live asset.
        """
        # Genuine bundle: superuser, ancient, the only real row for its name.
        stable = self._mk("p.gcb.esm.js", "/web/assets/esm/aaaa/p.gcb.esm.js", 400)
        # Phantom: same name, HIGHER id, created by a non-superuser admin.
        admin = self.env.ref("base.user_admin")
        self.assertNotEqual(admin.id, SUPERUSER_ID, "phantom must not be superuser")
        phantom = (
            self.env["ir.attachment"]
            .with_user(admin)
            .create(
                {
                    "name": "p.gcb.esm.js",
                    "url": "/web/assets/esm/bbbb/p.gcb.esm.js",
                    "type": "binary",
                    "public": True,
                    "res_model": "ir.ui.view",
                    "res_id": False,
                    "raw": b"/* phantom */",
                    "mimetype": "text/javascript",
                }
            )
        )
        self.assertGreater(phantom.id, stable.id, "phantom must have the higher id")

        self.env["ir.attachment"]._gc_esm_assets()

        self.assertTrue(
            stable.exists(),
            "the genuine stable bundle must survive a non-superuser phantom",
        )

    def test_gc_grace_floor(self):
        """A non-positive ``web.esm.gc_grace_days`` is floored, not honored.

        grace <= 0 would put the cutoff at/after now and sweep every bridge
        (no newest-per-name protection) on each run, including ones written
        moments ago. The floor keeps at least a day of grace.
        """
        self.env["ir.config_parameter"].sudo().set_param("web.esm.gc_grace_days", "0")
        fresh = self._mk(
            "0011223344556677.js", "/web/assets/esm/bridges/0011223344556677.js"
        )
        self.env["ir.attachment"]._gc_esm_assets()
        self.assertTrue(
            fresh.exists(), "a fresh bridge survives grace_days=0 (floored to 1)"
        )
