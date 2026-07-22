"""Tests for propagating the PO project onto its picking values."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPickingProject(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "PPS vendor"})
        cls.project = cls.env["project.project"].create({"name": "PPS project"})

    def _po(self, project=None):
        return self.env["purchase.order"].create(
            {
                "partner_id": self.partner.id,
                "project_id": project.id if project else False,
            }
        )

    def test_picking_vals_carry_project(self):
        """A PO tied to a project stamps that project on the picking values."""
        po = self._po(project=self.project)
        self.assertEqual(po._prepare_picking_vals()["project_id"], self.project.id)

    def test_picking_vals_without_project(self):
        """A PO with no project leaves the picking values without one (boundary)."""
        po = self._po(project=None)
        self.assertNotIn("project_id", po._prepare_picking_vals())
