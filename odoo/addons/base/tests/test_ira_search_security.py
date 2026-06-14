"""Adversarial access-control probes for ir.attachment._search.

The security path has two strategies: a per-model subquery domain
(``_search_models_security_domain``, used when no more than
``_SEARCH_MODEL_DOMAIN_LIMIT`` res_models are restricted) and a
fetch-and-filter fallback (``_fetch_accessible_ids``, for broad searches).
These tests pin that:

* both strategies expose exactly the rows the user may read (no leak, no loss);
* the fallback's batched OFFSET pagination over a caller order is total and
  stable — the appended ``id`` tiebreaker prevents skipping or duplicating rows
  whose sort key ties across a batch boundary.
"""

from unittest.mock import patch

from odoo.addons.base.models import ir_attachment as ira_module
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestIraSearchSecurity(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        # run as a real, non-system internal user so access rules apply
        self.env = self.env(user=self.user_demo)
        self.Attachment = self.env["ir.attachment"]

    def test_fallback_pagination_complete_and_unique(self):
        """Caller-ordered fallback pagination must not skip or duplicate rows.

        Forces the fetch-and-filter fallback (no res_model restriction) over
        several small batches with tied sort values; the appended id tiebreaker
        keeps the multi-batch OFFSET scan total, so every accessible row appears
        exactly once.
        """
        # demo's own res_id=False attachments are accessible to their creator;
        # give them all the SAME name so the 'name' sort is full of ties.
        created = self.Attachment.create([{"name": "DUPNAME"} for _ in range(7)])
        self.env.flush_all()
        created.invalidate_recordset()

        # PREFETCH_MAX rows per batch -> 2 forces 4 batches over the 7 rows
        with patch.object(ira_module, "PREFETCH_MAX", 2):
            found = self.Attachment.search([("name", "=", "DUPNAME")], order="name")

        self.assertEqual(len(found), 7, "every accessible row returned (none skipped)")
        self.assertEqual(len(set(found.ids)), 7, "no row duplicated across batches")
        self.assertEqual(set(found.ids), set(created.ids))

    def test_model_limit_paths_agree_on_access(self):
        """Per-model and fallback strategies expose the same accessible set.

        The _SEARCH_MODEL_DOMAIN_LIMIT boundary is an optimization, not a
        security boundary: an attachment on an unreadable record must be hidden
        whether the query restricts res_model (per-model path) or not (fallback).
        """
        partner_ok = self.env["res.partner"].sudo().create({"name": "P-ok"})
        partner_no = self.env["res.partner"].sudo().create({"name": "P-no"})
        a_ok = self.Attachment.sudo().create(
            {"name": "a-ok", "res_model": "res.partner", "res_id": partner_ok.id}
        )
        a_no = self.Attachment.sudo().create(
            {"name": "a-no", "res_model": "res.partner", "res_id": partner_no.id}
        )
        # global read rule hiding partner_no from the (non-super) demo user
        self.env["ir.rule"].sudo().create(
            {
                "name": "hide P-no",
                "model_id": self.env["ir.model"]._get_id("res.partner"),
                "domain_force": "[('id', '!=', %d)]" % partner_no.id,
                "perm_read": True,
            }
        )
        self.env.flush_all()
        (a_ok + a_no).invalidate_recordset()
        ids = (a_ok + a_no).ids

        # per-model path: res_model restricted to a single model
        per_model = self.Attachment.search(
            [("res_model", "=", "res.partner"), ("id", "in", ids)]
        )
        # fallback path: res_model unrestricted
        fallback = self.Attachment.search([("id", "in", ids)])

        self.assertEqual(per_model.ids, [a_ok.id], "per-model path hides a-no")
        self.assertEqual(fallback.ids, [a_ok.id], "fallback path hides a-no")

    def test_public_and_creator_visibility(self):
        """public rows are visible to all; private res_id=False only to creator."""
        admin = self.env.ref("base.user_admin")
        public = (
            self.env["ir.attachment"]
            .with_user(admin)
            .create({"name": "pub", "public": True})
        )
        private_other = (
            self.env["ir.attachment"]
            .with_user(admin)
            .create({"name": "priv", "public": False})
        )
        mine = self.Attachment.create({"name": "mine"})  # created by demo
        self.env.flush_all()
        (public + private_other + mine).invalidate_recordset()

        visible = self.Attachment.search([("name", "in", ["pub", "priv", "mine"])])
        self.assertIn(public.id, visible.ids, "public visible to everyone")
        self.assertNotIn(
            private_other.id,
            visible.ids,
            "private res_id=False hidden from non-creator",
        )
        self.assertIn(mine.id, visible.ids, "own res_id=False visible to creator")
