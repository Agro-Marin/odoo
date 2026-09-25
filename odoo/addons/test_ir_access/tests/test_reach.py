from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase

from odoo.addons.base.models.ir_access import filter_reads_user

MODEL = "test_ir_access.reached"


class TestReach(TransactionCase):
    # a row says how far it reaches through an anchor its model declares, and
    # compiles to the domain its text used to spell out

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.access"].search([("model_id.model", "=", MODEL)]).unlink()
        cls.group = cls.env["res.groups"].create({"name": "Reach"})
        cls.parent = cls.env["res.company"].create({"name": "Parent"})
        cls.child = cls.env["res.company"].create(
            {"name": "Child", "parent_id": cls.parent.id}
        )
        cls.other = cls.env["res.company"].create({"name": "Other"})
        cls.customer = cls.env["res.partner"].create(
            {"name": "Customer", "is_company": True}
        )
        cls.contact = cls.env["res.partner"].create(
            {"name": "Contact", "parent_id": cls.customer.id}
        )
        cls.user = cls.env["res.users"].create(
            {
                "login": "reacher",
                "name": "Reacher",
                "company_id": cls.child.id,
                "company_ids": [Command.set(cls.child.ids)],
                "group_ids": [
                    Command.set((cls.env.ref("base.group_user") + cls.group).ids)
                ],
            }
        )
        cls.user.partner_id.parent_id = cls.customer
        cls.stranger = cls.env["res.users"].create(
            {"login": "stranger", "name": "Stranger"}
        )
        Reached = cls.env[MODEL]
        cls.mine = Reached.create({"name": "mine", "user_id": cls.user.id})
        cls.theirs = Reached.create({"name": "theirs", "user_id": cls.stranger.id})
        cls.nobody = Reached.create({"name": "nobody"})
        cls.approving = Reached.create(
            {"name": "approving", "approver_ids": [Command.link(cls.user.id)]}
        )
        cls.my_partner = Reached.create(
            {"name": "my partner", "partner_id": cls.user.partner_id.id}
        )
        cls.colleague = Reached.create(
            {"name": "colleague", "partner_id": cls.contact.id}
        )
        cls.in_child = Reached.create({"name": "child", "company_id": cls.child.id})
        cls.in_parent = Reached.create({"name": "parent", "company_id": cls.parent.id})
        cls.in_other = Reached.create({"name": "other", "company_id": cls.other.id})
        cls.all = Reached.search([])

    def row(self, reach, anchor=None, domain=None, **values):
        return self.env["ir.access"].create(
            {
                "name": f"reach {reach}",
                "model_id": self.env["ir.model"]._get_id(MODEL),
                "group_id": self.group.id,
                "kind": "permission",
                "operation": "r",
                "reach": reach,
                "anchor": anchor,
                "domain": domain,
                **values,
            }
        )

    def reached(self):
        return self.env[MODEL].with_user(self.user).search([]) & self.all

    def test_own_reads_the_owner(self):
        self.row("own")
        self.assertEqual(self.reached(), self.mine)

    def test_a_shared_anchor_admits_the_unassigned(self):
        self.row("own", "assignee")
        self.assertEqual(self.reached(), self.all - self.theirs)

    def test_own_through_a_second_anchor(self):
        self.row("own", "approver")
        self.assertEqual(self.reached(), self.approving)

    def test_own_through_the_creator(self):
        mine = self.env[MODEL].with_user(self.user).sudo().create({"name": "created"})
        self.row("own", "creator")
        self.assertEqual(self.env[MODEL].with_user(self.user).search([]), mine)

    def test_own_through_the_partner_is_the_principal_s_own_contact(self):
        self.row("own", "partner")
        self.assertEqual(self.reached(), self.my_partner)

    def test_partner_reads_the_commercial_tree(self):
        self.row("partner")
        self.assertEqual(self.reached(), self.my_partner + self.colleague)

    def test_company_reads_the_companies_in_use_and_the_shared_records(self):
        self.row("company")
        self.assertEqual(self.reached(), self.all - self.in_parent - self.in_other)

    def test_a_company_anchor_can_read_up_the_tree(self):
        self.row("company", "parent_company")
        self.assertEqual(self.reached(), self.in_child + self.in_parent)

    def test_all_and_none(self):
        self.row("all")
        self.assertEqual(self.reached(), self.all)
        self.env["ir.access"].search([("model_id.model", "=", MODEL)]).unlink()
        self.row("none")
        # a row admitting nothing is no access to the model, as [(0, '=', 1)]
        self.assertFalse(self.env[MODEL].with_user(self.user).has_access("read"))

    def test_a_fixed_filter_rides_along(self):
        self.row("own", "assignee", domain="[('name', '!=', 'nobody')]")
        self.assertEqual(self.reached(), self.all - self.theirs - self.nobody)

    def test_a_template_predicate(self):
        predicate = self.env["ir.access.predicate"].create(
            {
                "name": "test.named_by",
                "template": "[('name', '=', args.name), ('user_id', 'in', [P.user])]",
            }
        )
        self.row(
            "predicate", predicate_id=predicate.id, predicate_args={"name": "mine"}
        )
        self.assertEqual(self.reached(), self.mine)

    def test_a_method_predicate(self):
        predicate = self.env["ir.access.predicate"].create(
            {
                "name": "test.named",
                "model_id": self.env["ir.model"]._get_id(MODEL),
                "method": "_access_predicate_named",
            }
        )
        self.row(
            "predicate", predicate_id=predicate.id, predicate_args={"name": "theirs"}
        )
        self.assertEqual(self.reached(), self.theirs)

    def test_the_explanation_says_the_reach(self):
        self.row("own", "approver")
        lines = self.env["ir.access"].with_user(self.user)._explain(MODEL, "read")
        self.assertTrue(any("approver_ids" in line for line in lines), lines)

    def test_an_anchor_the_model_does_not_declare_is_refused(self):
        with self.assertRaisesRegex(ValidationError, "does not declare"):
            self.row("team")

    def test_a_rung_that_cannot_read_the_anchor_is_refused(self):
        with self.assertRaisesRegex(ValidationError, "cannot read the anchor"):
            self.row("partner", "owner")

    def test_beside_a_reach_the_domain_reads_no_user(self):
        with self.assertRaisesRegex(ValidationError, "fixed filter"):
            self.row("own", domain="[('user_id', '=', user.id)]")

    def test_a_predicate_is_its_own_reach(self):
        predicate = self.env["ir.access.predicate"].create(
            {"name": "test.any", "template": "[]"}
        )
        with self.assertRaisesRegex(ValidationError, "Named predicate"):
            self.row("own", predicate_id=predicate.id)
        with self.assertRaisesRegex(ValidationError, "Named predicate"):
            self.row("predicate")

    def test_a_template_reads_only_the_principal_and_its_arguments(self):
        Predicate = self.env["ir.access.predicate"]
        with self.assertRaisesRegex(ValidationError, "reads only P and args"):
            Predicate.create({"name": "t1", "template": "[('id', '=', user.id)]"})
        with self.assertRaisesRegex(ValidationError, "the principal offers"):
            Predicate.create({"name": "t2", "template": "[('id', '=', P.password)]"})

    def test_the_anchors_are_checked_against_the_registry(self):
        anchors = self.env.registry.model_anchors[MODEL]
        self.assertEqual(anchors["approver"].kind, "owner")
        self.assertEqual(anchors["creator"].path, "create_uid")
        self.assertEqual(self.env[MODEL]._access_company_anchor(), "company_id")

    def test_a_filter_on_a_field_that_reads_the_user_is_no_fixed_filter(self):
        registry = self.env.registry
        self.assertTrue(filter_reads_user(registry, MODEL, "[('is_mine', '=', True)]"))
        self.assertFalse(filter_reads_user(registry, MODEL, "[('name', '=', 'x')]"))
        with self.assertRaises(ValidationError):
            self.row("all", domain="[('is_mine', '=', True)]")
        # what an earlier conversion left in a database: the reach all beside it
        row = self.row("all", domain="[('name', '!=', False)]")
        self.env.cr.execute(
            "UPDATE ir_access SET domain = %s WHERE id = %s",
            ["[('is_mine', '=', True)]", row.id],
        )
        row.invalidate_recordset()
        self.env["ir.access"]._clear_access_caches()
        self.assertEqual(self.reached(), self.mine)
        row._rows_to_reach()
        self.assertFalse(row.reach)
        self.assertEqual(self.reached(), self.mine)
