from odoo import models
from odoo.tests import tagged

from odoo.addons.pos_restaurant.tests.test_frontend import TestFrontendCommon


@tagged("post_install", "-at_install")
class TestPosRestaurantDataContract(TestFrontendCommon):
    """The payload contract for courses, driven through the real loader.

    `pos_order.test.js` covers the same code with a store built by
    `setupPosEnv()` and `store.addCourse()`, so the harness wires the relation
    itself and the test passes against a payload the server never sends. These
    go through `load_data_params()` instead, which is what the client reads.
    """

    def test_the_order_declares_every_field_this_module_adds_to_it(self):
        # ir.model.data is the ORM's own record of which module created a field,
        # so this follows the module rather than a hand-kept list that would
        # go stale the next time pos_restaurant extends pos.order.
        owned = self.env["ir.model.data"].search(
            [("module", "=", "pos_restaurant"), ("model", "=", "ir.model.fields")]
        )
        automatic = {"id", *models.LOG_ACCESS_COLUMNS}
        added = {
            f.name
            for f in self.env["ir.model.fields"].browse(owned.mapped("res_id"))
            if f.model == "pos.order" and f.store and f.name not in automatic
        }
        self.assertTrue(
            added, "pos_restaurant must be seen to add fields to pos.order at all"
        )
        declared = set(
            self.env["pos.order"]._load_pos_data_fields(self.main_pos_config)
        )

        self.assertFalse(
            added - declared,
            "the client builds its models from this list, so a field this module"
            " adds to pos.order and does not declare here reaches the browser as"
            " undefined and every read of it throws. The three this module adds"
            " are all read from the client -- table_id in 45 places,"
            f" customer_count in 13, course_ids in 11. Undeclared:"
            f" {sorted(added - declared)}",
        )

    def test_the_course_relation_reaches_the_client_under_its_orm_name(self):
        session = self.main_pos_config.current_session_id
        if not session:
            self.main_pos_config.with_user(self.pos_user).open_ui()
            session = self.main_pos_config.current_session_id

        relations = session.load_data_params()["pos.order"]["relations"]

        self.assertIn(
            "course_ids",
            relations,
            "without this entry the client's model layer falls back to an"
            " invented backref name for the courses it already received, so the"
            " records arrive linked but unreachable as `order.course_ids`",
        )
        self.assertEqual(
            relations["course_ids"]["relation"],
            "restaurant.order.course",
            "the courses the order ships must be the model the relation names",
        )

    def test_the_shipped_courses_have_something_to_attach_to(self):
        session = self.main_pos_config.current_session_id
        if not session:
            self.main_pos_config.with_user(self.pos_user).open_ui()
            session = self.main_pos_config.current_session_id
        params = session.load_data_params()

        self.assertIn(
            "restaurant.order.course",
            params,
            "read_pos_data ships these records, so the model has to be loaded",
        )
        relations = params["pos.order"]["relations"]
        self.assertIn(
            "course_ids",
            relations,
            "the courses are shipped, so the order has to name the relation that"
            " reaches them -- otherwise they arrive with nothing to attach to",
        )
        self.assertEqual(
            relations["course_ids"]["type"],
            "one2many",
            "the order side of the relation is the one the client reads",
        )
