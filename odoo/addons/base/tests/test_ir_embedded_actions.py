from odoo.exceptions import UserError

from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestEmbeddedActionsBase(TransactionCaseWithUserDemo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_partner = cls.env["res.partner"].create(
            {
                "city": "OrigCity",
                "email": "test.partner@test.example.com",
                "name": "TestingPartner",
                "employee": True,
            }
        )
        cls.context = {
            "active_model": "res.partner",
            "active_id": cls.test_partner.id,
        }

        cls.parent_action = cls.env["ir.actions.act_window"].create(
            {
                "name": "ParentAction",
                "res_model": "res.partner",
            }
        )

        cls.action_1 = cls.env["ir.actions.act_window"].create(
            {
                "name": "Action1",
                "res_model": "res.partner",
            }
        )
        cls.action_2 = cls.env["ir.actions.act_window"].create(
            {
                "name": "Action2",
                "res_model": "res.partner",
            }
        )

        cls.embedded_action_1 = cls.env["ir.embedded.actions"].create(
            {
                "name": "EmbeddedAction1",
                "parent_res_model": "res.partner",
                "parent_action_id": cls.parent_action.id,
                "action_id": cls.action_1.id,
            }
        )

        cls.embedded_action_2 = cls.env["ir.embedded.actions"].create(
            {
                "name": "EmbeddedAction1",
                "parent_res_model": "res.partner",
                "parent_action_id": cls.parent_action.id,
                "action_id": cls.action_2.id,
            }
        )

    def get_embedded_actions_ids(self, parent_action):
        return parent_action.with_context(self.context).read()[0]["embedded_action_ids"]

    def test_parent_has_embedded_actions(self):
        res = self.get_embedded_actions_ids(self.parent_action)
        self.assertEqual(
            len(res),
            2,
            "There should be 2 embedded records linked to the parent action",
        )
        self.assertTrue(
            self.embedded_action_1.id in res and self.embedded_action_2.id in res,
            "The correct embedded actions\
                        should be in embedded_actions",
        )

    def test_cannot_delete_default_embedded_action(self):
        # A record seeded from a data file (external id not __export__/__custom__)
        # is not deletable and must raise UserError on unlink.
        seeded_action = self.env["ir.embedded.actions"].create(
            {
                "name": "SeededEmbeddedAction",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_2.id,
            }
        )
        self.env["ir.model.data"].create(
            {
                "name": "seeded_embedded_action",
                "module": "base",
                "model": "ir.embedded.actions",
                "res_id": seeded_action.id,
            }
        )
        seeded_action.invalidate_recordset(["is_deletable"])
        self.assertFalse(
            seeded_action.is_deletable,
            "A record seeded from a data file should not be deletable",
        )
        with self.assertRaises(UserError):
            seeded_action.unlink()

    def test_python_method_visibility(self):
        # An embedded action whose python_method does not exist on the parent
        # model is hidden; one whose python_method exists is shown.
        invalid_method_action = self.env["ir.embedded.actions"].create(
            {
                "name": "InvalidMethodAction",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "python_method": "this_method_does_not_exist",
            }
        )
        valid_method_action = self.env["ir.embedded.actions"].create(
            {
                "name": "ValidMethodAction",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "python_method": "read",
            }
        )
        self.assertFalse(
            invalid_method_action.with_context(self.context).is_visible,
            "An embedded action with a non-existent python_method should be hidden",
        )
        self.assertTrue(
            valid_method_action.with_context(self.context).is_visible,
            "An embedded action with an existing python_method should be visible",
        )

    def test_malformed_domain_visibility(self):
        # A malformed domain literal must be caught (ValueError/SyntaxError) and
        # yield is_visible=False without raising a traceback.
        malformed_action = self.env["ir.embedded.actions"].create(
            {
                "name": "MalformedDomainAction",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_2.id,
                "domain": "[(",
            }
        )
        self.assertFalse(
            malformed_action.with_context(self.context).is_visible,
            "An embedded action with a malformed domain should be hidden",
        )

    def test_user_id_scoping_visibility(self):
        # A personal embedded action (user_id set) is visible only to its owner;
        # a shared action (user_id empty) is visible to any user.
        owner = self.user_demo
        other_user = self.env["res.users"].create(
            {
                "name": "OtherUser",
                "login": "other_user_embedded",
                "group_ids": [(6, 0, [self.ref("base.group_user")])],
            }
        )
        personal_action = self.env["ir.embedded.actions"].create(
            {
                "name": "PersonalEmbeddedAction",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_2.id,
                "user_id": owner.id,
            }
        )
        shared_action = self.env["ir.embedded.actions"].create(
            {
                "name": "SharedEmbeddedAction",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_1.id,
            }
        )
        self.assertTrue(
            personal_action.with_user(owner).with_context(self.context).is_visible,
            "A personal embedded action should be visible to its owner",
        )
        self.assertFalse(
            personal_action.with_user(other_user).with_context(self.context).is_visible,
            "A personal embedded action should be hidden from a non-owner",
        )
        self.assertTrue(
            shared_action.with_user(other_user).with_context(self.context).is_visible,
            "A shared embedded action should be visible to any user",
        )

    def test_active_model_gates_visibility(self):
        # Cross-model id collision: active_id names a record of the context's
        # active_model only, so an action on another parent_res_model stays
        # hidden even if that model's table holds a same-id record.
        # Root user (self.env.user) is active=False and the compute's search
        # would never find it, so use an active user.
        user = self.user_demo
        cross_model_action = self.env["ir.embedded.actions"].create(
            {
                "name": "CrossModelAction",
                "parent_res_model": "res.users",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_1.id,
            }
        )
        self.assertFalse(
            cross_model_action.with_context(
                active_model="res.partner", active_id=user.id
            ).is_visible,
            "An embedded action on another model than active_model should be hidden",
        )
        self.assertTrue(
            cross_model_action.with_context(
                active_model="res.users", active_id=user.id
            ).is_visible,
            "An embedded action matching active_model should stay visible",
        )
        # Flows passing only active_id keep the id-only matching behavior.
        self.assertTrue(
            cross_model_action.with_context(active_id=user.id).is_visible,
            "Without active_model, matching by active_id alone is preserved",
        )

    def test_can_delete_custom_embedded_action(self):
        embedded_action_custo = self.env["ir.embedded.actions"].create(
            {
                "name": "EmbeddedActionCusto",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_2.id,
            }
        )
        try:
            embedded_action_custo.unlink()
        except UserError:
            self.assertTrue(False)

    def test_domain_on_embedded_action(self):
        test_partner_custo = self.env["res.partner"].create(
            {
                "city": "CustoCity",
                "email": "test.partner@test.example.com",
                "name": "CustomPartner",
                "employee": False,
            }
        )
        self.context = {
            "active_model": "res.partner",
            "active_id": test_partner_custo.id,
        }
        embedded_action_custo = self.env["ir.embedded.actions"].create(
            {
                "name": "EmbeddedActionCusto",
                "parent_res_model": "res.partner",
                "parent_action_id": self.parent_action.id,
                "action_id": self.action_2.id,
                "domain": [("employee", "=", True)],
            }
        )
        res = self.get_embedded_actions_ids(self.parent_action)
        self.assertTrue(
            embedded_action_custo.id not in res,
            "The embedded action not respecting the domain should\
                         not be returned in the read method",
        )

    def test_groups_on_embedded_action(self):
        nested_arbitrary_group = self.env["res.groups"].create(
            {
                "name": "arbitrary_group",
                "implied_ids": [(6, 0, [self.ref("base.group_user")])],
            }
        )
        arbitrary_group = self.env["res.groups"].create(
            {
                "name": "arbitrary_group",
                "implied_ids": [(6, 0, [nested_arbitrary_group.id])],
            }
        )
        embedded_action1, embedded_action2 = self.env["ir.embedded.actions"].create(
            [
                {
                    "name": "EmbeddedActionCusto",
                    "parent_res_model": "res.partner",
                    "parent_action_id": self.parent_action.id,
                    "action_id": self.action_2.id,
                    "group_ids": [(6, 0, [nested_arbitrary_group.id])],
                },
                {
                    "name": "EmbeddedActionCusto2",
                    "parent_res_model": "res.partner",
                    "parent_action_id": self.parent_action.id,
                    "action_id": self.action_2.id,
                    "group_ids": [(6, 0, [arbitrary_group.id])],
                },
            ]
        )
        res = self.get_embedded_actions_ids(self.parent_action)
        self.assertEqual(
            len(res),
            2,
            "There should be 2 embedded records linked to the parent action",
        )
        self.assertTrue(
            self.embedded_action_1.id in res and self.embedded_action_2.id in res,
            "The correct embedded actions\
                        should be in embedded_actions",
        )
        self.env.user.write({"group_ids": [(4, arbitrary_group.id)]})
        res = self.get_embedded_actions_ids(self.parent_action)
        self.assertEqual(
            len(res),
            4,
            "There should be 4 embedded records linked to the parent action",
        )
        self.assertTrue(
            self.embedded_action_1.id in res
            and self.embedded_action_2.id in res
            and embedded_action1.id in res
            and embedded_action2.id in res,
            "The correct embedded actions should be in embedded_actions",
        )

    def test_create_embedded_action_with_action_and_python_method(self):
        embedded_action1, embedded_action2 = self.env["ir.embedded.actions"].create(
            [
                {
                    "name": "EmbeddedActionCustom",
                    "action_id": self.action_2.id,
                    "parent_action_id": self.parent_action.id,
                    "parent_res_model": "res.partner",
                    "python_method": "action_python_method",
                },
                {
                    "name": "EmbeddedActionCustom2",
                    "action_id": self.action_2.id,
                    "python_method": "",
                    "parent_action_id": self.parent_action.id,
                    "parent_res_model": "res.partner",
                },
            ]
        )
        self.assertEqual(embedded_action1.python_method, "action_python_method")
        self.assertFalse(embedded_action1.action_id)
        self.assertEqual(
            embedded_action2.action_id,
            self.env["ir.actions.actions"].browse(self.action_2.id),
        )
        self.assertFalse(embedded_action2.python_method)
