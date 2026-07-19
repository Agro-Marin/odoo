from datetime import date
from unittest.mock import patch

import requests
from markupsafe import Markup
from psycopg import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.libs.json import OPT_SORT_KEYS
from odoo.libs.json import dumps as json_dumps
from odoo.tests import common, tagged
from odoo.tools import mute_logger

from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestServerActionsBase(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()

        # Data on which we will run the server action
        self.test_country = self.env["res.country"].create(
            {
                "name": "TestingCountry",
                "code": "TY",
                "address_format": "SuperFormat",
                "name_position": "before",
            }
        )
        self.test_partner = self.env["res.partner"].create(
            {
                "city": "OrigCity",
                "country_id": self.test_country.id,
                "email": "test.partner@test.example.com",
                "name": "TestingPartner",
            }
        )
        self.context = {
            "active_model": "res.partner",
            "active_id": self.test_partner.id,
        }

        # Model data
        Model = self.env["ir.model"]
        Fields = self.env["ir.model.fields"]
        self.comment_html = "<p>MyComment</p>"
        self.res_partner_model = Model.search([("model", "=", "res.partner")])
        self.res_partner_name_field = Fields.search(
            [("model", "=", "res.partner"), ("name", "=", "name")]
        )
        self.res_partner_city_field = Fields.search(
            [("model", "=", "res.partner"), ("name", "=", "city")]
        )
        self.res_partner_country_field = Fields.search(
            [("model", "=", "res.partner"), ("name", "=", "country_id")]
        )
        self.res_partner_parent_field = Fields.search(
            [("model", "=", "res.partner"), ("name", "=", "parent_id")]
        )
        self.res_partner_children_field = Fields.search(
            [("model", "=", "res.partner"), ("name", "=", "child_ids")]
        )
        self.res_partner_category_field = Fields.search(
            [("model", "=", "res.partner"), ("name", "=", "category_id")]
        )
        self.res_country_model = Model.search([("model", "=", "res.country")])
        self.res_country_name_field = Fields.search(
            [("model", "=", "res.country"), ("name", "=", "name")]
        )
        self.res_country_code_field = Fields.search(
            [("model", "=", "res.country"), ("name", "=", "code")]
        )
        self.res_country_name_position_field = Fields.search(
            [("model", "=", "res.country"), ("name", "=", "name_position")]
        )
        self.res_partner_category_model = Model.search(
            [("model", "=", "res.partner.category")]
        )
        self.res_partner_category_name_field = Fields.search(
            [("model", "=", "res.partner.category"), ("name", "=", "name")]
        )

        # server action exercised by the tests
        self.action = self.env["ir.actions.server"].create(
            {
                "name": "TestAction",
                "model_id": self.res_partner_model.id,
                "model_name": "res.partner",
                "state": "code",
                "code": 'record.write({"comment": "%s"})' % self.comment_html,
            }
        )

        server_action_model = Model.search([("model", "=", "ir.actions.server")])
        self.test_server_action = self.env["ir.actions.server"].create(
            {
                "name": "TestDummyServerAction",
                "model_id": server_action_model.id,
                "state": "code",
                "code": """
_logger.log(10, "This is a %s debug %s", "test", "log")
_logger.info("This is a %s info %s", "test", "log")
_logger.warning("This is a %s warning %s", "test", "log")
_logger.error("This is a %s error %s", "test", "log")
try:
    0/0
except:
    _logger.exception("This is a %s exception %s", "test", "log")
""",
            }
        )


class TestServerActions(TestServerActionsBase):
    def test_00_server_action(self):
        with self.assertLogs(
            "odoo.addons.base.models.ir_actions.server_action_safe_eval",
            level="DEBUG",
        ) as log_catcher:
            self.test_server_action.run()
            self.assertEqual(
                log_catcher.output,
                [
                    "DEBUG:odoo.addons.base.models.ir_actions.server_action_safe_eval:This is a test debug log",
                    "INFO:odoo.addons.base.models.ir_actions.server_action_safe_eval:This is a test info log",
                    "WARNING:odoo.addons.base.models.ir_actions.server_action_safe_eval:This is a test warning log",
                    "ERROR:odoo.addons.base.models.ir_actions.server_action_safe_eval:This is a test error log",
                    """ERROR:odoo.addons.base.models.ir_actions.server_action_safe_eval:This is a test exception log
Traceback (most recent call last):
  File "ir.actions.server(%d,)", line 6, in <module>
ZeroDivisionError: division by zero"""
                    % self.test_server_action.id,
                ],
            )

    def test_00_action(self):
        self.action.with_context(self.context).run()
        self.assertEqual(
            self.test_partner.comment,
            self.comment_html,
            "ir_actions_server: invalid condition check",
        )
        self.test_partner.write({"comment": False})

        # Do: create contextual action
        self.action.create_action()
        self.assertEqual(self.action.binding_model_id.model, "res.partner")

        # Do: remove contextual action
        self.action.unlink_action()
        self.assertFalse(self.action.binding_model_id)

    def test_10_code(self):
        self.action.write(
            {
                "state": "code",
                "code": (
                    "partner_name = record.name + '_code'\nrecord.env['res.partner'].create({'name': partner_name})"
                ),
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: code server action correctly finished should return False",
        )

        partners = self.test_partner.search([("name", "ilike", "TestingPartner_code")])
        self.assertEqual(
            len(partners),
            1,
            "ir_actions_server: 1 new partner should have been created",
        )

    def test_20_crud_create(self):
        # Do: create a new record in another model
        self.action.write(
            {
                "state": "object_create",
                "crud_model_id": self.res_partner_model.id,
                "link_field_id": False,
                "value": "TestingPartner2",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: create record action correctly finished should return False",
        )
        # Test: new partner created
        partner = self.test_partner.search([("name", "ilike", "TestingPartner2")])
        self.assertEqual(len(partner), 1, "ir_actions_server: TODO")

    def test_20_crud_create_link_many2one(self):

        # Do: create a new record in the same model and link it with a many2one
        self.action.write(
            {
                "state": "object_create",
                "crud_model_id": self.res_partner_model.id,
                "link_field_id": self.res_partner_parent_field.id,
                "value": "TestNew",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: create record action correctly finished should return False",
        )
        # Test: new partner created
        partner = self.test_partner.search([("name", "ilike", "TestNew")])
        self.assertEqual(len(partner), 1, "ir_actions_server: TODO")
        # Test: new partner linked
        self.assertEqual(
            self.test_partner.parent_id, partner, "ir_actions_server: TODO"
        )

    def test_20_crud_create_link_one2many(self):

        # Do: create a new record in the same model and link it with a one2many
        self.action.write(
            {
                "state": "object_create",
                "crud_model_id": self.res_partner_model.id,
                "link_field_id": self.res_partner_children_field.id,
                "value": "TestNew",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: create record action correctly finished should return False",
        )
        # Test: new partner created
        partner = self.test_partner.search([("name", "ilike", "TestNew")])
        self.assertEqual(len(partner), 1, "ir_actions_server: TODO")
        self.assertEqual(partner.name, "TestNew", "ir_actions_server: TODO")
        # Test: new partner linked
        self.assertIn(partner, self.test_partner.child_ids, "ir_actions_server: TODO")

    def test_20_crud_create_link_many2many(self):
        # Do: create a new record in another model
        self.action.write(
            {
                "state": "object_create",
                "crud_model_id": self.res_partner_category_model.id,
                "link_field_id": self.res_partner_category_field.id,
                "value": "TestingPartner",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: create record action correctly finished should return False",
        )
        # Test: new category created
        category = self.env["res.partner.category"].search(
            [("name", "ilike", "TestingPartner")]
        )
        self.assertEqual(len(category), 1, "ir_actions_server: TODO")
        self.assertIn(category, self.test_partner.category_id)

    def test_25_crud_copy(self):
        self.action.write(
            {
                "state": "object_copy",
                "crud_model_id": self.res_partner_model.id,
                "resource_ref": self.test_partner,
            }
        )
        partner = self.env["res.partner"].search(
            [("name", "ilike", self.test_partner.name)]
        )
        self.assertEqual(len(partner), 1)
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: duplicate record action correctly finished should return False",
        )
        partner = self.env["res.partner"].search(
            [("name", "ilike", self.test_partner.name)]
        )
        self.assertEqual(len(partner), 2)

    def test_25_crud_copy_link_many2one(self):
        self.action.write(
            {
                "state": "object_copy",
                "crud_model_id": self.res_partner_model.id,
                "resource_ref": self.test_partner,
                "link_field_id": self.res_partner_parent_field.id,
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: duplicate record action correctly finished should return False",
        )
        dupe = self.test_partner.search(
            [
                ("name", "ilike", self.test_partner.name),
                ("id", "!=", self.test_partner.id),
            ]
        )
        self.assertEqual(len(dupe), 1)
        self.assertEqual(self.test_partner.parent_id, dupe)

    def test_25_crud_copy_link_one2many(self):
        self.action.write(
            {
                "state": "object_copy",
                "crud_model_id": self.res_partner_model.id,
                "resource_ref": self.test_partner,
                "link_field_id": self.res_partner_children_field.id,
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: duplicate record action correctly finished should return False",
        )
        dupe = self.test_partner.search(
            [
                ("name", "ilike", self.test_partner.name),
                ("id", "!=", self.test_partner.id),
            ]
        )
        self.assertEqual(len(dupe), 1)
        self.assertIn(dupe, self.test_partner.child_ids)

    def test_25_crud_copy_link_many2many(self):
        category_id = self.env["res.partner.category"].name_create(
            "CategoryToDuplicate"
        )[0]
        self.action.write(
            {
                "state": "object_copy",
                "crud_model_id": self.res_partner_category_model.id,
                "link_field_id": self.res_partner_category_field.id,
                "resource_ref": f"res.partner.category,{category_id}",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: duplicate record action correctly finished should return False",
        )
        dupe = self.env["res.partner.category"].search(
            [
                ("name", "ilike", "CategoryToDuplicate"),
                ("id", "!=", category_id),
            ]
        )
        self.assertEqual(len(dupe), 1)
        self.assertIn(dupe, self.test_partner.category_id)

    def test_30_crud_write(self):
        # Do: update partner name
        self.action.write(
            {
                "state": "object_write",
                "update_path": "name",
                "value": "TestNew",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: create record action correctly finished should return False",
        )
        # Test: partner updated
        partner = self.test_partner.search([("name", "ilike", "TestNew")])
        self.assertEqual(len(partner), 1, "ir_actions_server: TODO")
        self.assertEqual(partner.city, "OrigCity", "ir_actions_server: TODO")

    def test_31_crud_write_html(self):
        self.assertEqual(self.action.value, False)
        self.action.write(
            {
                "state": "object_write",
                "update_path": "comment",
                "html_value": "<p>MyComment</p>",
            }
        )
        self.assertEqual(self.action.html_value, Markup("<p>MyComment</p>"))
        # Test run
        self.assertEqual(self.test_partner.comment, False)
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: create record action correctly finished should return False",
        )
        self.assertEqual(self.test_partner.comment, Markup("<p>MyComment</p>"))

    def test_object_write_equation(self):
        # Do: update partners city
        self.action.write(
            {
                "state": "object_write",
                "update_path": "city",
                "evaluation_type": "equation",
                "value": "record.id",
            }
        )
        partners = self.test_partner + self.test_partner.copy()
        self.action.with_context(self.context, active_ids=partners.ids).run()
        # Test: partners updated
        self.assertEqual(partners[0].city, str(partners[0].id))
        self.assertEqual(partners[1].city, str(partners[1].id))

    def test_35_crud_write_selection(self):
        # res.partner has no plain selection field, so use a dedicated res.country action
        # Do: update country name_position field
        selection_value = self.res_country_name_position_field.selection_ids.filtered(
            lambda s: s.value == "after"
        )
        action = self.env["ir.actions.server"].create(
            {
                "name": "TestAction",
                "model_id": self.res_country_model.id,
                "model_name": "res.country",
                "state": "object_write",
                "update_path": "name_position",
                "selection_value": selection_value.id,
            }
        )
        action._set_selection_value()  # manual onchange
        self.assertEqual(action.value, selection_value.value)
        context = {
            "active_model": "res.country",
            "active_id": self.test_country.id,
        }
        run_res = action.with_context(context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: country updated
        self.assertEqual(self.test_country.name_position, "after")

    def test_36_crud_write_m2m_ops(self):
        """Test that m2m operations work as expected"""
        categ_1 = self.env["res.partner.category"].create({"name": "TestCateg1"})
        categ_2 = self.env["res.partner.category"].create({"name": "TestCateg2"})
        # set partner category
        self.action.write(
            {
                "state": "object_write",
                "update_path": "category_id",
                "update_m2m_operation": "set",
                "resource_ref": categ_1,
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertIn(
            categ_1,
            self.test_partner.category_id,
            "ir_actions_server: tag should have been set",
        )

        # add partner category
        self.action.write(
            {
                "state": "object_write",
                "update_path": "category_id",
                "update_m2m_operation": "add",
                "resource_ref": categ_2,
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertIn(
            categ_2,
            self.test_partner.category_id,
            "ir_actions_server: new tag should have been added",
        )
        self.assertIn(
            categ_1,
            self.test_partner.category_id,
            "ir_actions_server: old tag should still be there",
        )

        # remove partner category
        self.action.write(
            {
                "state": "object_write",
                "update_path": "category_id",
                "update_m2m_operation": "remove",
                "resource_ref": categ_1,
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertNotIn(
            categ_1,
            self.test_partner.category_id,
            "ir_actions_server: tag should have been removed",
        )
        self.assertIn(
            categ_2,
            self.test_partner.category_id,
            "ir_actions_server: tag should still be there",
        )

        # clear partner category
        self.action.write(
            {
                "state": "object_write",
                "update_path": "category_id",
                "update_m2m_operation": "clear",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertFalse(
            self.test_partner.category_id,
            "ir_actions_server: tags should have been cleared",
        )

    def test_37_field_path_traversal(self):
        """Test the update_path field traversal - allowing records to be updated along relational links"""
        # update the country's name via the partner
        self.action.write(
            {
                "state": "object_write",
                "update_path": "country_id.name",
                "value": "TestUpdatedCountry",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertEqual(
            self.test_partner.country_id.name,
            "TestUpdatedCountry",
            "ir_actions_server: country name should have been updated through relation",
        )

        # update a readonly field
        self.action.write(
            {
                "state": "object_write",
                "update_path": "country_id.image_url",
                "value": "/base/static/img/country_flags/be.png",
            }
        )
        self.assertEqual(
            self.test_partner.country_id.image_url,
            "/base/static/img/country_flags/ty.png",
            "ir_actions_server: country flag has this value before the update",
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertEqual(
            self.test_partner.country_id.image_url,
            "/base/static/img/country_flags/be.png",
            "ir_actions_server: country should have been updated through a readonly field",
        )
        self.assertEqual(
            self.test_partner.country_id.code,
            "TY",
            "ir_actions_server: country code is still TY",
        )

        # input an invalid path
        with self.assertRaises(ValidationError):
            self.action.write(
                {
                    "state": "object_write",
                    "update_path": "country_id.name.foo",
                    "value": "DoesNotMatter",
                }
            )
            self.action.flush_recordset(["update_path", "update_field_id"])

    def test_39_boolean_update(self):
        """Test that boolean fields can be updated"""
        # update the country's name via the partner
        self.action.write(
            {
                "state": "object_write",
                "update_path": "active",
                "update_boolean_value": "false",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertFalse(
            self.test_partner.active,
            "ir_actions_server: partner should have been deactivated",
        )
        self.action.write(
            {
                "state": "object_write",
                "update_path": "active",
                "update_boolean_value": "true",
            }
        )
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(
            run_res,
            "ir_actions_server: update record action correctly finished should return False",
        )
        # Test: partner updated
        self.assertTrue(
            self.test_partner.active,
            "ir_actions_server: partner should have been reactivated",
        )

    @mute_logger("odoo.addons.base.models.ir_model", "odoo.models")
    def test_40_multi(self):
        # Data: 2 server actions that will be nested
        action1 = self.action.create(
            {
                "name": "Subaction1",
                "sequence": 1,
                "model_id": self.res_partner_model.id,
                "state": "code",
                "code": 'action = {"type": "ir.actions.act_window"}',
            }
        )
        action2 = self.action.create(
            {
                "name": "Subaction2",
                "sequence": 2,
                "model_id": self.res_partner_model.id,
                "crud_model_id": self.res_partner_model.id,
                "state": "object_create",
                "value": "RaoulettePoiluchette",
            }
        )
        action3 = self.action.create(
            {
                "name": "Subaction2",
                "sequence": 3,
                "model_id": self.res_partner_model.id,
                "state": "object_write",
                "update_path": "city",
                "value": "RaoulettePoiluchette",
            }
        )
        action4 = self.action.create(
            {
                "name": "Subaction3",
                "sequence": 4,
                "model_id": self.res_partner_model.id,
                "state": "code",
                "code": 'action = {"type": "ir.actions.act_url"}',
            }
        )
        self.action.write(
            {
                "state": "multi",
                "child_ids": [
                    Command.set([action1.id, action2.id, action3.id, action4.id])
                ],
            }
        )

        # Do: run the action
        res = self.action.with_context(self.context).run()

        # Test: new partner created
        # currently res_partner overrides default['name'] whatever its value
        partner = self.test_partner.search([("name", "ilike", "RaoulettePoiluchette")])
        self.assertEqual(len(partner), 1)
        # Test: action returned
        self.assertEqual(res.get("type"), "ir.actions.act_url")

        # Test loops
        with self.assertRaises(ValidationError):
            self.action.write({"child_ids": [Command.set([self.action.id])]})

    def test_50_groups(self):
        """check the action is returned only for groups dedicated to user"""
        Actions = self.env["ir.actions.actions"]

        group0 = self.env["res.groups"].create({"name": "country group"})

        self.context = {
            "active_model": "res.country",
            "active_id": self.test_country.id,
        }

        # Do: update model and group
        self.action.write(
            {
                "model_id": self.res_country_model.id,
                "binding_model_id": self.res_country_model.id,
                "group_ids": [Command.link(group0.id)],
                "code": 'record.write({"vat_label": "VatFromTest"})',
            }
        )

        # Test: action is not returned
        bindings = Actions.get_bindings("res.country")
        self.assertFalse(bindings)

        with self.assertRaises(AccessError):
            self.action.with_context(self.context).run()
        self.assertFalse(self.test_country.vat_label)

        # add group to the user, and test again
        self.env.user.write({"group_ids": [Command.link(group0.id)]})

        bindings = Actions.get_bindings("res.country")
        self.assertItemsEqual(
            bindings.get("action"),
            self.action.read(["name", "sequence", "binding_view_types"]),
        )

        self.action.with_context(self.context).run()
        self.assertEqual(
            self.test_country.vat_label,
            "VatFromTest",
            "vat label should be changed to VatFromTest",
        )

    def test_60_sort(self):
        """check the actions sorted by sequence"""
        Actions = self.env["ir.actions.actions"]

        # Do: update model
        self.action.write(
            {
                "model_id": self.res_country_model.id,
                "binding_model_id": self.res_country_model.id,
            }
        )
        self.action2 = self.action.copy({"name": "TestAction2", "sequence": 1})

        # Test: action returned by sequence
        bindings = Actions.get_bindings("res.country")
        self.assertEqual(
            [vals.get("name") for vals in bindings["action"]],
            ["TestAction2", "TestAction"],
        )
        self.assertEqual([vals.get("sequence") for vals in bindings["action"]], [1, 5])

    def test_70_copy_action(self):
        # first check that the base case (reset state) works normally
        r = self.env["ir.actions.todo"].create(
            {
                "action_id": self.action.id,
                "state": "done",
            }
        )
        self.assertEqual(r.state, "done")
        self.assertEqual(
            r.copy().state, "open", "by default state should be reset by copy"
        )

        # then check that on server action we've changed that
        self.assertEqual(
            self.action.copy().state,
            "code",
            "copying a server action should not reset the state",
        )

    def test_80_permission(self):
        self.action.write(
            {
                "state": "code",
                "code": """record.write({'name': str(datetime.date.today())})""",
            }
        )

        user_demo = self.user_demo
        self_demo = self.action.with_user(user_demo.id)

        # can write on contact partner
        self.test_partner.type = "contact"
        self.test_partner.with_user(user_demo.id).check_access("write")

        self_demo.with_context(self.context).run()
        self.assertEqual(self.test_partner.name, str(date.today()))

    def test_90_webhook(self):
        self.action.write(
            {
                "state": "webhook",
                "webhook_field_ids": [
                    Command.link(self.res_partner_name_field.id),
                    Command.link(self.res_partner_city_field.id),
                    Command.link(self.res_partner_country_field.id),
                ],
                "webhook_url": "http://example.com/webhook",
            }
        )
        # mock requests.post: assert the payload, return 200 then 400
        num_requests = 0

        def _patched_post(*args, **kwargs):
            nonlocal num_requests
            response = requests.Response()
            response.status_code = 200 if num_requests == 0 else 400
            self.assertEqual(args[0], "http://example.com/webhook")
            self.assertEqual(
                kwargs["data"],
                json_dumps(
                    {
                        "_action": "%s(#%s)" % (self.action.name, self.action.id),
                        "_id": self.test_partner.id,
                        "_model": self.test_partner._name,
                        "city": self.test_partner.city,
                        "country_id": self.test_partner.country_id.id,
                        "id": self.test_partner.id,
                        "name": self.test_partner.name,
                    },
                    default=str,
                    option=OPT_SORT_KEYS,
                ),
            )
            num_requests += 1
            return response

        with (
            patch.object(requests, "post", _patched_post),
            mute_logger("odoo.addons.base.models.ir_actions_server"),
        ):
            # first run: 200
            self.action.with_context(self.context).run()
            self.env.cr.postcommit.run()  # webhooks run in postcommit
            # second run: 400, should *not* raise but
            # should warn in logs (hence mute_logger)
            self.action.with_context(self.context).run()
            self.env.cr.postcommit.run()  # webhooks run in postcommit
        self.assertEqual(num_requests, 2)

    def test_90_convert_to_float(self):
        # make sure eval_value convert the value into float for float-type fields
        self.action.write(
            {
                "state": "object_write",
                "update_path": "partner_latitude",
                "value": "20.99",
            }
        )
        self.assertEqual(self.action._eval_value()[self.action.id], 20.99)

    def test_91_update_related_model_cleared_on_state_change(self):
        """update_related_model_id must be cleared when switching away from object_write."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "country_id",
                "evaluation_type": "value",
            }
        )
        self.action.flush_recordset()
        self.assertTrue(
            self.action.update_related_model_id,
            "update_related_model_id should be set for a relational update_path",
        )
        # Switch to object_create — update_related_model_id must be cleared
        self.action.write({"state": "object_create"})
        self.action.flush_recordset()
        self.assertFalse(
            self.action.update_related_model_id,
            "update_related_model_id should be cleared when state changes to object_create",
        )

    def test_92_relation_chain_duplicate_field_names(self):
        """_get_relation_chain must handle paths with repeated field names (e.g. parent_id.parent_id)."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "parent_id.parent_id",
            }
        )
        self.action.flush_recordset()
        # update_field_id must be the second parent_id (last in the chain),
        # not the first one.
        self.assertEqual(
            self.action.update_field_id.name,
            "parent_id",
            "update_field_id should be the last field in the path",
        )
        self.assertEqual(
            self.action.crud_model_id.model,
            "res.partner",
            "crud_model_id should be res.partner (parent_id is self-referential)",
        )

    def test_93_webhook_timeout(self):
        """A webhook read timeout must not escape postcommit; it is logged."""
        self.action.write(
            {
                "state": "webhook",
                "webhook_url": "http://example.com/webhook",
            }
        )

        def _patched_post(*args, **kwargs):
            raise requests.exceptions.ReadTimeout("timed out")

        with patch.object(requests, "post", _patched_post):
            self.action.with_context(self.context).run()
            with self.assertLogs(
                "odoo.addons.base.models.ir_actions_server", level="WARNING"
            ) as log_catcher:
                # Must not raise even though requests.post timed out.
                self.env.cr.postcommit.run()
        self.assertTrue(
            any("timed out" in line for line in log_catcher.output),
            "the read timeout should be logged as a warning",
        )

    def test_94_webhook_connection_error(self):
        """A webhook connection error must not escape postcommit; it is logged."""
        self.action.write(
            {
                "state": "webhook",
                "webhook_url": "http://example.com/webhook",
            }
        )

        def _patched_post(*args, **kwargs):
            raise requests.exceptions.ConnectionError("connection refused")

        with patch.object(requests, "post", _patched_post):
            self.action.with_context(self.context).run()
            with self.assertLogs(
                "odoo.addons.base.models.ir_actions_server", level="WARNING"
            ) as log_catcher:
                # Must not raise even though requests.post failed.
                self.env.cr.postcommit.run()
        self.assertTrue(
            any("Webhook call failed" in line for line in log_catcher.output),
            "the connection error should be logged as a warning",
        )

    def test_95_code_sandbox_blocked(self):
        """The safe_eval sandbox must reject forbidden constructs in a code action."""
        # `import os` is rejected by the _check_python_code constraint at write time.
        with self.assertRaises(ValidationError):
            self.action.write(
                {
                    "state": "code",
                    "code": "import os\nos.system('echo pwned')",
                }
            )
        # `open(...)` is not whitelisted in the sandbox builtins: it raises at run time.
        self.action.write(
            {
                "state": "code",
                "code": "open('/etc/passwd').read()",
            }
        )
        # `open` (not a sandbox builtin) raises NameError, which safe_eval
        # re-wraps as ValueError. Pass a single class: assertRaises uses
        # issubclass() and rejects a tuple.
        with self.assertRaises(ValueError):
            self.action.with_context(self.context).run()

    def test_96_eval_value_m2m_bad_value(self):
        """A non-numeric m2m value must not raise; it yields a no-op command list."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "category_id",
                "update_m2m_operation": "add",
                "value": "not-an-int",
            }
        )
        # _eval_value must not raise on a non-numeric value for an m2m operation.
        self.assertEqual(self.action._eval_value()[self.action.id], [])
        # Running the action is a no-op rather than a crash.
        run_res = self.action.with_context(self.context).run()
        self.assertFalse(run_res)

    def test_97_eval_value_m2m_unknown_operation(self):
        """An unknown/falsy m2m operation must leave the field untouched (no-op)."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "category_id",
                "update_m2m_operation": False,
                "value": "1",
            }
        )
        # No matching match-case: expr stays the default empty command list.
        self.assertEqual(self.action._eval_value()[self.action.id], [])

    def test_98_object_write_no_path_errors(self):
        """object_write with neither onchange_self nor update_path raises."""
        # Clear update_path afterwards to mimic an action with nothing to update.
        self.action.write(
            {
                "state": "object_write",
                "update_path": "name",
                "value": "X",
            }
        )
        self.action.update_path = False
        with self.assertRaises(UserError):
            self.action.with_context(self.context).run()

    def test_99_object_copy_no_resource_ref_errors(self):
        """object_copy with an empty resource_ref raises a clean UserError."""
        self.action.write(
            {
                "state": "object_copy",
                "crud_model_id": self.res_partner_model.id,
                "resource_ref": self.test_partner,
            }
        )
        self.action.resource_ref = False
        with self.assertRaises(UserError):
            self.action.with_context(self.context).run()

    def test_a0_relation_chain_unknown_field(self):
        """An unknown field in update_path raises a translated ValidationError."""
        with self.assertRaises(ValidationError):
            self.action.write(
                {
                    "state": "object_write",
                    "update_path": "does_not_exist",
                    "value": "X",
                }
            )
            self.action.flush_recordset(["update_path", "update_field_id"])

    def test_a1_create_action_access(self):
        """A non-writer calling create_action raises AccessError."""
        self.action.write(
            {
                "model_id": self.res_partner_model.id,
                "binding_model_id": False,
            }
        )
        with self.assertRaises(AccessError):
            self.action.with_user(self.user_demo.id).create_action()

    def test_a2_write_blank_code_records_history(self):
        """Blanking a code action's code records a history entry (mirrors create)."""
        History = self.env["ir.actions.server.history"]
        before = History.search_count([("action_id", "=", self.action.id)])
        self.action.write({"code": ""})
        after = History.search_count([("action_id", "=", self.action.id)])
        self.assertEqual(
            after,
            before + 1,
            "clearing the code should record a history entry",
        )

    def test_a3_active_less_non_code_run_warns(self):
        """A non-``code`` action run with no active record warns instead of
        no-op'ing silently.

        Every runner except ``code`` needs a target record; with empty
        ``active_ids`` the per-record loop never iterates (e.g. a cron pointed at
        an ``object_write``). Assert a warning naming the action is emitted and
        the record is left untouched.
        """
        self.action.write(
            {
                "state": "object_write",
                "update_path": "name",
                "value": "ShouldNotApply",
            }
        )
        original_name = self.test_partner.name
        logger = "odoo.addons.base.models.ir_actions_server"
        # Run with NO active_model/active_id/active_ids in context (cron-style).
        with self.assertLogs(logger, level="WARNING") as log_catcher:
            self.action.run()
        self.assertTrue(
            any("was triggered with no target record" in m for m in log_catcher.output),
            "an active-less non-code action must warn, not silently no-op",
        )
        self.assertEqual(
            self.test_partner.name,
            original_name,
            "no record was targeted, so nothing should have been written",
        )

    def test_a4_active_less_code_run_does_not_warn(self):
        """A ``code`` action is the one type that legitimately runs without a
        target record (its runner is ``_multi``), so it must NOT emit the
        no-target warning."""
        code_action = self.env["ir.actions.server"].create(
            {
                "name": "ActiveLessCode",
                "model_id": self.res_partner_model.id,
                "state": "code",
                "code": "x = 1",
            }
        )
        logger = "odoo.addons.base.models.ir_actions_server"
        with self.assertNoLogs(logger, level="WARNING"):
            code_action.run()

    def test_b0_eval_value_bad_integer_raises_clean_error(self):
        """A non-numeric static value for an integer field raises a clean UserError,
        never leaking the raw string into write() (which would crash with ValueError)."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "color",  # integer field on res.partner
                "evaluation_type": "value",
                "value": "not_a_number",
            }
        )
        with self.assertRaises(UserError):
            self.action._eval_value()

    def test_b1_eval_value_bad_float_raises_clean_error(self):
        """A non-numeric static value for a float field raises a clean UserError."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "partner_latitude",  # float field
                "evaluation_type": "value",
                "value": "not_a_number",
            }
        )
        with self.assertRaises(UserError):
            self.action._eval_value()

    def test_b2_eval_value_blank_numeric_is_typed_zero(self):
        """A blank static value degrades to a typed empty (0 / False), not a crash."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "color",
                "evaluation_type": "value",
                "value": "",
            }
        )
        self.assertEqual(self.action._eval_value()[self.action.id], 0)
        # many2one blank -> False (clear the relation)
        self.action.write({"update_path": "parent_id", "value": ""})
        self.assertIs(self.action._eval_value()[self.action.id], False)

    def test_b3_relation_chain_degrades_without_raising_on_read(self):
        """_get_relation_chain must NOT raise on an invalid path by default, so that
        stored computes (crud_model_id, warning) can never explode on plain read."""
        # .new() bypasses constraints, letting us hold an invalid path in-memory.
        action = self.env["ir.actions.server"].new(
            {
                "model_id": self.res_partner_model.id,
                "state": "object_write",
                "update_path": "totally_not_a_field",
            }
        )
        # Must degrade to an empty chain rather than raise.
        self.assertEqual(action._get_relation_chain("update_path"), ([], ""))
        # And crud_model_id (a stored compute) must be readable without raising.
        self.assertFalse(action.update_field_id)

    def test_b4_empty_path_segment_raises_clear_error_on_save(self):
        """A path with an empty segment (double dot) is rejected on save with a
        message that names the empty segment, not a baffling "Unknown field ''"."""
        with self.assertRaises(ValidationError) as cm:
            self.action.write(
                {
                    "state": "object_write",
                    "update_path": "parent_id..name",
                    "value": "X",
                }
            )
            self.action.flush_recordset(["update_path", "update_field_id"])
        self.assertIn("empty", str(cm.exception).lower())

    def test_b5_available_models_not_state_dependent(self):
        """available_model_ids is state-invariant, so it must not declare a
        dependency on `state` (which would force a needless ir.model search on
        every state change)."""
        compute = type(self.env["ir.actions.server"])._compute_available_model_ids
        self.assertNotIn("state", getattr(compute, "_depends", ()))

    def test_b6_equation_evaluates_without_sudo_privilege(self):
        """SECURITY INVARIANT: an expression must evaluate with the triggering
        user's own privilege (``env.su`` False), so record ACLs still apply. The
        dispatch runs sudo, but the per-record eval-context env must stay the
        user's env, NOT ``run_self.env`` (sudo) — that would bypass ACLs."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "color",  # integer field
                "evaluation_type": "equation",
                "value": "1 if env.su else 0",
                # group-gate so the demo user is authorized without needing a
                # record-level ACL grant (see _can_execute_action_on_records)
                "group_ids": [Command.set(self.env.ref("base.group_user").ids)],
            }
        )
        self.action.with_user(self.user_demo.id).with_context(self.context).run()
        self.assertEqual(
            self.test_partner.color,
            0,
            "expressions must evaluate with su=False (user ACLs), not elevated",
        )

    def test_b7_onchange_new_record_writes_cache_only(self):
        """An object_write action triggered as an onchange on a NEW record (no
        origin id) must set the value in the record's in-memory cache via the
        early-return branch of _run, never touching the database."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "function",  # char field on res.partner
                "evaluation_type": "value",
                "value": "Set By Action",
            }
        )
        new_record = self.env["res.partner"].new({"name": "New Guy"})
        self.assertFalse(new_record._origin.id, "precondition: unsaved record")
        self.action.with_context(
            active_model="res.partner", onchange_self=new_record
        ).run()
        self.assertEqual(new_record.function, "Set By Action")

    def test_b8_onchange_existing_record_writes_cache_not_db(self):
        """An object_write onchange on an EXISTING record updates only the
        in-memory cache of the edited pseudo-record; the persisted row is left
        untouched (onchange must never write to the database)."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "function",
                "evaluation_type": "value",
                "value": "Set By Action",
            }
        )
        onchange_record = self.env["res.partner"].new(
            {"name": self.test_partner.name}, origin=self.test_partner
        )
        self.assertTrue(onchange_record._origin.id, "precondition: has origin")
        self.action.with_context(
            active_model="res.partner", onchange_self=onchange_record
        ).run()
        self.assertEqual(onchange_record.function, "Set By Action")
        self.assertFalse(
            self.test_partner.function,
            "onchange must not persist to the database record",
        )

    def test_c0_eval_value_sequence(self):
        """evaluation_type == 'sequence' draws the next value from the sequence."""
        sequence = self.env["ir.sequence"].create(
            {"name": "Test Seq", "prefix": "SEQ-", "padding": 4, "number_next": 1}
        )
        self.action.write(
            {
                "state": "object_write",
                "update_path": "ref",  # a char field, as the sequence warning requires
                "evaluation_type": "sequence",
                "sequence_id": sequence.id,
            }
        )
        value = self.action._eval_value()[self.action.id]
        self.assertEqual(value, "SEQ-0001")

    def test_c1_eval_value_blank_float_is_typed_zero(self):
        """A blank value on a float field yields 0.0, not '' (mirrors test_b2 for int)."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "partner_latitude",
                "evaluation_type": "value",
                "value": "",
            }
        )
        result = self.action._eval_value()[self.action.id]
        self.assertEqual(result, 0.0)
        self.assertIsInstance(result, float)

    def test_c2_eval_value_m2o_parsed_zero_is_false(self):
        """A value that parses to 0 on a many2one field clears the relation (False),
        not a spurious id 0."""
        self.action.write(
            {
                "state": "object_write",
                "update_path": "country_id",
                "evaluation_type": "value",
                "value": "0",
            }
        )
        self.assertIs(self.action._eval_value()[self.action.id], False)

    def test_c3_gc_histories_prunes_to_max(self):
        """The autovacuum keeps at most ``_max_entries_per_action`` rows per action."""
        History = self.env["ir.actions.server.history"]
        action = self.env["ir.actions.server"].create(
            {
                "name": "GC target",
                "model_id": self.res_partner_model.id,
                "state": "code",
                "code": "x = 1",
            }
        )
        # Start from a clean slate (create() already recorded one entry), then add
        # more than the cap directly so the pruning has something to trim.
        History.search([("action_id", "=", action.id)]).unlink()
        cap = History._max_entries_per_action
        History.create(
            [{"action_id": action.id, "code": str(i)} for i in range(cap + 5)]
        )
        self.assertEqual(History.search_count([("action_id", "=", action.id)]), cap + 5)
        History._gc_histories()
        self.assertEqual(
            History.search_count([("action_id", "=", action.id)]),
            cap,
            "GC must prune each action's history down to the cap",
        )

    def test_c4_webhook_sample_payload_structure(self):
        """The webhook sample payload always carries _id/_model/_action plus the
        selected fields, as valid JSON."""
        import json

        self.action.write(
            {
                "state": "webhook",
                "webhook_url": "http://example.invalid/hook",
                "webhook_field_ids": [Command.set([self.res_partner_name_field.id])],
            }
        )
        payload = json.loads(self.action.webhook_sample_payload)
        self.assertEqual(payload["_model"], "res.partner")
        self.assertIn("_id", payload)
        self.assertIn("_action", payload)
        self.assertIn("name", payload)

    def test_c5_record_level_acl_is_the_live_gate(self):
        """For a groupless action, the triggering user's write access on the
        concrete records is the real gate (the model-level check runs under the
        sudo dispatch env and never blocks). A user lacking record write access
        is refused with a logged AccessError."""
        rule_model = self.env["ir.model"].search([("model", "=", "ir.rule")])
        a_rule = self.env["ir.rule"].search([], limit=1)
        self.assertTrue(a_rule, "precondition: at least one ir.rule exists")
        self.assertFalse(
            self.env["ir.rule"].with_user(self.user_demo).has_access("write"),
            "precondition: demo user cannot write ir.rule",
        )
        action = self.env["ir.actions.server"].create(
            {
                "name": "Touch a rule",
                "model_id": rule_model.id,
                "state": "code",
                "code": "x = 1",
            }
        )
        with (
            self.assertRaises(AccessError),
            mute_logger("odoo.addons.base.models.ir_actions_server"),
        ):
            action.with_user(self.user_demo).with_context(
                active_model="ir.rule",
                active_id=a_rule.id,
                active_ids=[a_rule.id],
            ).run()


@tagged("post_install", "-at_install")
class TestActionsPath(common.TransactionCase):
    """Cover _check_path format/reserved/cross-table uniqueness (IACT-T1)."""

    def _make_window(self, path):
        return self.env["ir.actions.act_window"].create(
            {
                "name": "PathWindow",
                "res_model": "res.partner",
                "path": path,
            }
        )

    def test_path_invalid_format(self):
        """The path must be lowercase alnum/_/- starting with a letter."""
        for bad in ("Foo", "1abc", "a b", "-abc"):
            with self.subTest(path=bad), self.assertRaises(ValidationError):
                self._make_window(bad)

    def test_path_reserved_prefixes(self):
        """The reserved prefixes/literal must be rejected."""
        for bad in ("m-foo", "action-foo", "new"):
            with self.subTest(path=bad), self.assertRaises(ValidationError):
                self._make_window(bad)

    def test_path_valid(self):
        """A well-formed, unused path is accepted."""
        action = self._make_window("my-valid_path1")
        self.assertEqual(action.path, "my-valid_path1")

    def test_path_unique_cross_table(self):
        """The same path on an act_window and an act_url is rejected cross-table.

        This proves the parent-table _read_group constraint spans child tables
        (the PG unique index only fires per child table).
        """
        self._make_window("shared-path")
        with self.assertRaises(ValidationError):
            self.env["ir.actions.act_url"].create(
                {
                    "name": "PathUrl",
                    "url": "https://example.com",
                    "path": "shared-path",
                }
            )


class TestActionsReadAndXmlId(common.TransactionCase):
    """Cover act_window.read help path and _for_xml_id guard (IACT-T2)."""

    def test_read_help_with_bad_context(self):
        """A malformed/non-dict context degrades to {}; help still populated."""
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "HelpWindow",
                "res_model": "res.partner",
                # non-dict context: read() must fall back to {} and not raise
                "context": "[1, 2, 3]",
                "help": "<p>Custom help</p>",
            }
        )
        values = action.read(["help", "res_model", "context"])[0]
        self.assertIn("help", values)
        self.assertIsNotNone(values["help"])

    def test_read_help_with_raising_context(self):
        """A context that raises on eval degrades to {}; help still populated."""
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "HelpWindow2",
                "res_model": "res.partner",
                # references an undefined name -> safe_eval raises -> fallback {}
                "context": "{'k': undefined_name}",
                "help": "<p>Custom help</p>",
            }
        )
        values = action.read(["help", "res_model", "context"])[0]
        self.assertIn("help", values)
        self.assertIsNotNone(values["help"])

    def test_read_help_only_field_enriches(self):
        """read(['help']) enriches help identically to a full read.

        Enrichment sources res_model/context from the record, so it no longer
        depends on those fields being present in the requested field list.
        """
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "HelpOnly",
                "res_model": "res.partner",
                "help": "<p>raw</p>",
            }
        )
        full = action.read(["help", "res_model", "context"])[0]["help"]
        only = action.read(["help"])[0]["help"]
        self.assertEqual(only, full)

    def test_for_xml_id_valid_window(self):
        """_for_xml_id of a valid window returns a dict limited to readable fields."""
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "XmlIdWindow",
                "res_model": "res.partner",
            }
        )
        # a freshly-created action has no external id; create one so the lookup resolves
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "test_for_xml_id_valid_window_action",
                "model": "ir.actions.act_window",
                "res_id": action.id,
            }
        )
        xml_id = "base.test_for_xml_id_valid_window_action"
        result = self.env["ir.actions.act_window"]._for_xml_id(xml_id)
        self.assertIsInstance(result, dict)
        readable = action._get_readable_fields()
        self.assertTrue(set(result.keys()).issubset(readable))

    def test_for_xml_id_non_action_raises(self):
        """_for_xml_id of a non-action xml_id raises ValidationError."""
        with self.assertRaises(ValidationError):
            # base.model_res_partner is an ir.model record, not an action.
            self.env["ir.actions.actions"]._for_xml_id("base.model_res_partner")

    def test_get_action_dict_act_url_no_invalid_field_warning(self):
        """act_url._get_action_dict() must not warn about virtual fields (IRA-L2).

        'close' is in the readable-fields allowlist but is not an ORM field;
        feeding it to read() used to log 'Invalid field(s) [...]' on every load.
        """
        action = self.env["ir.actions.act_url"].create(
            {"name": "UrlAction", "url": "https://example.com"}
        )
        self.assertNotIn("close", action._fields)
        with self.assertNoLogs("odoo.models", "WARNING"):
            result = action._get_action_dict()
        # the virtual key was never produced by read(), so it stays absent
        self.assertNotIn("close", result)
        # every returned key is a real, readable field
        self.assertTrue(set(result) <= action._get_readable_fields())
        self.assertTrue(set(result) <= set(action._fields))

    def test_get_action_dict_window_close_no_invalid_field_warning(self):
        """act_window_close._get_action_dict() must not warn (IRA-L2).

        'effect'/'infos' are readable but virtual (not ORM fields).
        """
        action = self.env["ir.actions.act_window_close"].create({"name": "CloseAction"})
        self.assertNotIn("effect", action._fields)
        self.assertNotIn("infos", action._fields)
        with self.assertNoLogs("odoo.models", "WARNING"):
            result = action._get_action_dict()
        self.assertNotIn("effect", result)
        self.assertNotIn("infos", result)

    def test_write_binding_irrelevant_field_skips_cache_clear(self):
        """Writing only binding-irrelevant fields must not clear the cache (IRA-L3).

        Writing a binding input (e.g. name) still must.
        """
        action = self.env["ir.actions.act_url"].create(
            {"name": "CacheAction", "url": "https://example.com"}
        )
        Registry = type(self.env.registry)

        def clears_for(vals):
            with patch.object(Registry, "clear_cache") as spy:
                action.write(vals)
            return spy.call_count

        self.assertEqual(
            clears_for({"help": "<p>irrelevant to bindings</p>"}),
            0,
            "writing only binding-irrelevant fields should not clear the cache",
        )
        self.assertGreaterEqual(
            clears_for({"name": "Renamed"}),
            1,
            "writing a binding input (name) must clear the cache",
        )

    def test_write_server_action_value_field_skips_cache_clear(self):
        """Editing an ir.actions.server runtime-value field (e.g. Python code)
        must not wipe the registry cache; a binding input still must (IRA-L3).
        """
        model = self.env["ir.model"]._get("res.partner")
        action = self.env["ir.actions.server"].create(
            {
                "name": "SrvCacheAction",
                "model_id": model.id,
                "state": "code",
                "code": "records.write({})",
            }
        )
        Registry = type(self.env.registry)

        def clears_for(vals):
            with patch.object(Registry, "clear_cache") as spy:
                action.write(vals)
            return spy.call_count

        self.assertEqual(
            clears_for({"code": "records.write({'active': True})"}),
            0,
            "editing a server action's code must not clear the registry cache",
        )
        self.assertGreaterEqual(
            clears_for({"binding_model_id": model.id}),
            1,
            "writing a binding input must clear the cache",
        )


class TestClientActionParams(common.TransactionCase):
    """Cover ir.actions.client params (de)serialization (IACT-T3)."""

    def test_params_roundtrip_dict(self):
        """A dict assigned to params is stored and read back unchanged."""
        action = self.env["ir.actions.client"].create(
            {"name": "ClientAction", "tag": "some_tag", "params": {"a": 1, "b": "x"}}
        )
        action.invalidate_recordset(["params"])
        self.assertEqual(action.params, {"a": 1, "b": "x"})

    def test_params_empty_store(self):
        """An empty params_store yields a falsy params without evaluating."""
        action = self.env["ir.actions.client"].create(
            {"name": "ClientAction2", "tag": "some_tag"}
        )
        self.assertFalse(action.params)

    def test_params_corrupt_store_degrades(self):
        """A corrupt params_store must not crash the action (IRA-L5).

        params_store is normally a repr()'d dict, but a malformed value (bad
        import / manual DB edit) must degrade to False, not raise, so the
        client action stays loadable via _get_action_dict/read.
        """
        action = self.env["ir.actions.client"].create(
            {"name": "ClientAction3", "tag": "some_tag"}
        )
        # write an un-evaluable value directly to the stored field
        action.params_store = "this is ( not valid python"
        action.invalidate_recordset(["params"])
        self.assertFalse(action.params)
        # and it stays readable end-to-end (the path that used to crash)
        with self.assertNoLogs("odoo.models", "WARNING"):
            data = action._get_action_dict()
        self.assertIn("params", data)


class TestActionsBindings(common.TransactionCase):
    """Cover get_bindings ordering and cache invalidation (IACT-T4)."""

    def _partner_model_id(self):
        return self.env["ir.model"]._get_id("res.partner")

    def _server(self, name, binding_type, sequence):
        return self.env["ir.actions.server"].create(
            {
                "name": name,
                "model_id": self._partner_model_id(),
                "state": "code",
                "code": "pass",
                "binding_model_id": self._partner_model_id(),
                "binding_type": binding_type,
                "sequence": sequence,
            }
        )

    def _binding_names(self, bucket):
        self.env.registry.clear_cache()
        bindings = self.env["ir.actions.actions"]._get_bindings("res.partner")
        return [d["name"] for d in bindings.get(bucket, ())]

    def test_report_bucket_sorted_by_sequence(self):
        """Server actions bound as 'report' are ordered by sequence.

        Regression: _get_bindings previously sorted only the 'action' bucket,
        leaving sequenced server-actions-as-reports in raw insertion order.
        """
        self._server("Zeta report", "report", 30)
        self._server("Alpha report", "report", 10)
        ordered = [
            n
            for n in self._binding_names("report")
            if n in ("Zeta report", "Alpha report")
        ]
        self.assertEqual(ordered, ["Alpha report", "Zeta report"])

    def test_action_bucket_sorted_by_sequence(self):
        """The 'action' bucket stays ordered by sequence."""
        self._server("Zeta action", "action", 30)
        self._server("Alpha action", "action", 10)
        ordered = [
            n
            for n in self._binding_names("action")
            if n in ("Zeta action", "Alpha action")
        ]
        self.assertEqual(ordered, ["Alpha action", "Zeta action"])

    def test_cache_safe_fields_disjoint_from_binding_inputs(self):
        """_CACHE_SAFE_FIELDS must exclude every field _get_bindings consumes.

        If a binding input were wrongly marked cache-safe, write() would skip
        invalidation and get_bindings would serve stale data. This locks the
        invariant that the _CACHE_SAFE_FIELDS comment only states informally.
        """
        binding_inputs = {
            "name",
            "type",
            "binding_model_id",
            "binding_type",
            "binding_view_types",
            "res_model",
            "group_ids",
            "sequence",
            "domain",
        }
        safe = self.env["ir.actions.actions"]._CACHE_SAFE_FIELDS
        overlap = safe & binding_inputs
        self.assertFalse(
            overlap,
            "cache-safe set overlaps binding inputs %s; writing them would "
            "leave stale bindings" % sorted(overlap),
        )

    def test_rename_bound_action_invalidates_bindings(self):
        """Renaming a bound action surfaces in get_bindings (no stale cache).

        This is the functional guard behind test_cache_safe_fields_disjoint:
        it fails outright if 'name' ever becomes cache-safe.
        """
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "BindOrig",
                "res_model": "res.partner",
                "binding_model_id": self._partner_model_id(),
            }
        )
        self.assertIn("BindOrig", self._binding_names("action"))
        action.write({"name": "BindRenamed"})
        names = self._binding_names("action")
        self.assertIn("BindRenamed", names)
        self.assertNotIn("BindOrig", names)

    def test_group_ids_resolved_to_xml_ids(self):
        """group_ids in bindings are external-id strings across many actions."""
        gid = self.env.ref("base.group_user").id
        for i in range(3):
            self.env["ir.actions.act_window"].create(
                {
                    "name": "Grp%d" % i,
                    "res_model": "res.partner",
                    "binding_model_id": self._partner_model_id(),
                    "group_ids": [Command.set([gid])],
                }
            )
        self.env.registry.clear_cache()
        raw = self.env["ir.actions.actions"]._get_bindings("res.partner")
        ours = [d for d in raw.get("action", ()) if d["name"].startswith("Grp")]
        self.assertEqual(len(ours), 3)
        for data in ours:
            self.assertEqual(data["group_ids"], ["base.group_user"])


class TestCommonCustomFields(common.TransactionCase):
    MODEL = "res.partner"
    COMODEL = "res.users"

    def setUp(self):
        # check that the registry is properly reset
        fnames = set(self.registry[self.MODEL]._fields)

        @self.addCleanup
        def check_registry():
            assert set(self.registry[self.MODEL]._fields) == fnames

        self.addCleanup(self.registry.reset_changes)
        self.addCleanup(self.registry.clear_all_caches)

        super().setUp()

    def create_field(self, name, *, field_type="char"):
        """create a custom field and return it"""
        model = self.env["ir.model"].search([("model", "=", self.MODEL)])
        field = self.env["ir.model.fields"].create(
            {
                "model_id": model.id,
                "name": name,
                "field_description": name,
                "ttype": field_type,
            }
        )
        self.assertIn(name, self.env[self.MODEL]._fields)
        return field

    def create_view(self, name):
        """create a view with the given field name"""
        return self.env["ir.ui.view"].create(
            {
                "name": "yet another view",
                "model": self.MODEL,
                "arch": '<list string="X"><field name="%s"/></list>' % name,
            }
        )


class TestCustomFields(TestCommonCustomFields):
    def test_create_custom(self):
        """custom field names must start with 'x_'"""
        with self.assertRaises(IntegrityError), mute_logger("odoo.db"):
            self.create_field("xyz")

    def test_rename_custom(self):
        """custom field names must start with 'x_'"""
        field = self.create_field("x_xyz")
        with self.assertRaises(IntegrityError), mute_logger("odoo.db"):
            field.name = "xyz"

    def test_create_valid(self):
        """field names must be valid pg identifiers"""
        with self.assertRaises(ValidationError):
            self.create_field("x_foo bar")

    def test_rename_valid(self):
        """field names must be valid pg identifiers"""
        field = self.create_field("x_foo")
        with self.assertRaises(ValidationError):
            field.name = "x_foo bar"

    def test_create_unique(self):
        """one cannot create two fields with the same name on a given model"""
        self.create_field("x_foo")
        with self.assertRaises(IntegrityError), mute_logger("odoo.db"):
            self.create_field("x_foo")

    def test_rename_unique(self):
        """one cannot create two fields with the same name on a given model"""
        field1 = self.create_field("x_foo")
        field2 = self.create_field("x_bar")
        with self.assertRaises(IntegrityError), mute_logger("odoo.db"):
            field2.name = field1.name

    def test_remove_without_view(self):
        """try removing a custom field that does not occur in views"""
        field = self.create_field("x_foo")
        field.unlink()

    def test_rename_without_view(self):
        """try renaming a custom field that does not occur in views"""
        field = self.create_field("x_foo")
        field.name = "x_bar"

    @mute_logger("odoo.addons.base.models.ir_ui_view")
    def test_remove_with_view(self):
        """try removing a custom field that occurs in a view"""
        field = self.create_field("x_foo")
        self.create_view("x_foo")

        # try to delete the field, this should fail but not modify the registry
        with self.assertRaises(UserError):
            field.unlink()
        self.assertIn("x_foo", self.env[self.MODEL]._fields)

    @mute_logger("odoo.addons.base.models.ir_ui_view")
    def test_rename_with_view(self):
        """try renaming a custom field that occurs in a view"""
        field = self.create_field("x_foo")
        self.create_view("x_foo")

        # try to delete the field, this should fail but not modify the registry
        with self.assertRaises(UserError):
            field.name = "x_bar"
        self.assertIn("x_foo", self.env[self.MODEL]._fields)

    def test_unlink_base(self):
        """one cannot delete a non-custom field expect for uninstallation"""
        field = self.env["ir.model.fields"]._get(self.MODEL, "ref")
        self.assertTrue(field)

        with self.assertRaisesRegex(UserError, "This column contains module data"):
            field.unlink()

        # but it works in the context of uninstalling a module
        field.with_context(_force_unlink=True).unlink()

    def test_unlink_with_inverse(self):
        """create a custom o2m and then delete its m2o inverse"""
        model = self.env["ir.model"]._get(self.MODEL)
        comodel = self.env["ir.model"]._get(self.COMODEL)

        m2o_field = self.env["ir.model.fields"].create(
            {
                "model_id": comodel.id,
                "name": "x_my_m2o",
                "field_description": "my_m2o",
                "ttype": "many2one",
                "relation": self.MODEL,
            }
        )

        o2m_field = self.env["ir.model.fields"].create(
            {
                "model_id": model.id,
                "name": "x_my_o2m",
                "field_description": "my_o2m",
                "ttype": "one2many",
                "relation": self.COMODEL,
                "relation_field": m2o_field.name,
            }
        )

        # normal mode: you cannot break dependencies
        with self.assertRaises(UserError):
            m2o_field.unlink()

        # uninstall mode: unlink dependant fields
        m2o_field.with_context(_force_unlink=True).unlink()
        self.assertFalse(o2m_field.exists())

    def test_unlink_with_dependant(self):
        """create a computed field, then delete its dependency"""
        # Also applies to compute fields
        comodel = self.env["ir.model"].search([("model", "=", self.COMODEL)])

        field = self.create_field("x_my_char")

        dependant = self.env["ir.model.fields"].create(
            {
                "model_id": comodel.id,
                "name": "x_oh_boy",
                "field_description": "x_oh_boy",
                "ttype": "char",
                "related": "partner_id.x_my_char",
            }
        )

        # normal mode: you cannot break dependencies
        with self.assertRaises(UserError):
            field.unlink()

        # uninstall mode: unlink dependant fields
        field.with_context(_force_unlink=True).unlink()
        self.assertFalse(dependant.exists())

    def test_unlink_inherited_custom(self):
        """Creating a field on a model automatically creates an inherited field
        in the comodel, and the latter can only be removed by deleting the
        "parent" field.
        """
        field = self.create_field("x_foo")
        self.assertEqual(field.state, "manual")

        inherited_field = self.env["ir.model.fields"]._get(self.COMODEL, "x_foo")
        self.assertTrue(inherited_field)
        self.assertEqual(inherited_field.state, "base")

        # one cannot delete the inherited field itself
        with self.assertRaises(UserError):
            inherited_field.unlink()

        # but the inherited field is deleted when its parent field is
        field.unlink()
        self.assertFalse(field.exists())
        self.assertFalse(inherited_field.exists())
        self.assertFalse(
            self.env["ir.model.fields"].search_count(
                [
                    ("model", "in", [self.MODEL, self.COMODEL]),
                    ("name", "=", "x_foo"),
                ]
            )
        )

    def test_create_binary(self):
        """binary custom fields should be created as attachment=True to avoid
        bloating the DB when creating e.g. image fields via studio
        """
        self.create_field("x_image", field_type="binary")
        custom_binary = self.env[self.MODEL]._fields["x_image"]

        self.assertTrue(custom_binary.attachment)

    def test_related_field(self):
        """create a custom related field, and check filled values"""
        # Equivalent to: x_oh_boy = fields.Char(related="country_id.code", store=True)

        # pick N=100 records in comodel
        countries = self.env["res.country"].search([("code", "!=", False)], limit=100)
        self.assertEqual(
            len(countries), 100, "Not enough records in comodel 'res.country'"
        )

        # create records in model, with N distinct values for the related field
        partners = self.env["res.partner"].create(
            [{"name": country.code, "country_id": country.id} for country in countries]
        )
        self.env.flush_all()

        # create a non-computed field, and assert how many queries it takes.
        # The baseline includes schema-time validation of res.partner's GIN
        # indexes (complete_name trigram, barcode) triggered by the registry
        # reload — paid only on reload, not per request.
        model_id = self.env["ir.model"]._get_id("res.partner")
        query_count = 57
        with self.assertQueryCount(query_count):
            self.env.registry.clear_cache()
            self.env["ir.model.fields"].create(
                {
                    "model_id": model_id,
                    "name": "x_oh_box",
                    "field_description": "x_oh_box",
                    "ttype": "char",
                    "store": True,
                }
            )

        # same with a related field, it only takes 6 extra queries
        with self.assertQueryCount(query_count + 6):
            self.env.registry.clear_cache()
            self.env["ir.model.fields"].create(
                {
                    "model_id": model_id,
                    "name": "x_oh_boy",
                    "field_description": "x_oh_boy",
                    "ttype": "char",
                    "related": "country_id.code",
                    "store": True,
                }
            )

        # check the computed values
        for partner in partners:
            self.assertEqual(partner.x_oh_boy, partner.country_id.code)

    def test_relation_of_a_custom_field(self):
        """change the relation model of a custom field"""
        model = self.env["ir.model"].search([("model", "=", self.MODEL)])
        field = self.env["ir.model.fields"].create(
            {
                "name": "x_foo",
                "model_id": model.id,
                "field_description": "x_foo",
                "ttype": "many2many",
                "relation": self.COMODEL,
            }
        )

        # change the relation
        with self.assertRaises(ValidationError):
            field.relation = "foo"

    def test_selection(self):
        """custom selection field"""
        Model = self.env[self.MODEL]
        model = self.env["ir.model"].search([("model", "=", self.MODEL)])
        field = self.env["ir.model.fields"].create(
            {
                "model_id": model.id,
                "name": "x_sel",
                "field_description": "Custom Selection",
                "ttype": "selection",
                "selection_ids": [
                    Command.create({"value": "foo", "name": "Foo", "sequence": 0}),
                    Command.create({"value": "bar", "name": "Bar", "sequence": 1}),
                ],
            }
        )

        x_sel = Model._fields["x_sel"]
        self.assertEqual(x_sel.type, "selection")
        self.assertEqual(x_sel.selection, [("foo", "Foo"), ("bar", "Bar")])

        # add selection value 'baz'
        field.selection_ids.create(
            {
                "field_id": field.id,
                "value": "baz",
                "name": "Baz",
                "sequence": 2,
            }
        )
        x_sel = Model._fields["x_sel"]
        self.assertEqual(x_sel.type, "selection")
        self.assertEqual(
            x_sel.selection, [("foo", "Foo"), ("bar", "Bar"), ("baz", "Baz")]
        )

        # assign values to records
        rec1 = Model.create({"name": "Rec1", "x_sel": "foo"})
        rec2 = Model.create({"name": "Rec2", "x_sel": "bar"})
        rec3 = Model.create({"name": "Rec3", "x_sel": "baz"})
        self.assertEqual(rec1.x_sel, "foo")
        self.assertEqual(rec2.x_sel, "bar")
        self.assertEqual(rec3.x_sel, "baz")

        # remove selection value 'foo'
        field.selection_ids[0].unlink()
        x_sel = Model._fields["x_sel"]
        self.assertEqual(x_sel.type, "selection")
        self.assertEqual(x_sel.selection, [("bar", "Bar"), ("baz", "Baz")])

        self.assertEqual(rec1.x_sel, False)
        self.assertEqual(rec2.x_sel, "bar")
        self.assertEqual(rec3.x_sel, "baz")

        # update selection value 'bar'
        field.selection_ids[0].value = "quux"
        x_sel = Model._fields["x_sel"]
        self.assertEqual(x_sel.type, "selection")
        self.assertEqual(x_sel.selection, [("quux", "Bar"), ("baz", "Baz")])

        self.assertEqual(rec1.x_sel, False)
        self.assertEqual(rec2.x_sel, "quux")
        self.assertEqual(rec3.x_sel, "baz")


@tagged("post_install", "-at_install")
class TestCustomFieldsPostInstall(TestCommonCustomFields):
    def test_add_field_valid(self):
        """custom field names must start with 'x_', even when bypassing the constraints

        If a user bypasses all constraints to add a custom field not starting by `x_`,
        it must not be loaded in the registry.

        This is to forbid users to override class attributes.
        """
        field = self.create_field("x_foo")
        # Drop the SQL constraint, to bypass it,
        # as a user could do through a SQL shell or a `cr.execute` in a server action
        self.env.cr.execute(
            "ALTER TABLE ir_model_fields DROP CONSTRAINT ir_model_fields_name_manual_field"
        )
        self.env.cr.execute(
            "UPDATE ir_model_fields SET name = 'foo' WHERE id = %s", [field.id]
        )
        with self.assertLogs("odoo.registry") as log_catcher:
            # Trick to reload the registry. The above rename done through SQL didn't reload the registry. This will.
            self.env.registry._setup_models__(self.cr, [self.MODEL])
            self.assertIn(
                f"The field `{field.name}` is not defined in the `{field.model}` Python class",
                log_catcher.output[0],
            )
