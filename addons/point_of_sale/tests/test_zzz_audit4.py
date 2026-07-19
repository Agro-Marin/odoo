# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Regression tests for the point_of_sale JS/security audit (round 4). Each test
# pins a fixed defect and was authored red-green: it failed against the pre-fix
# code and passes after the fix.
import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestAudit4Security(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def _base_order_vals(self, session, uuid, **extra):
        return {
            "uuid": uuid,
            "session_id": session.id,
            "company_id": self.env.company.id,
            "config_id": self.config.id,
            "user_id": self.env.uid,
            "state": "draft",
            "amount_total": 0,
            "amount_tax": 0,
            "amount_paid": 0,
            "amount_return": 0,
            "lines": [],
            "payment_ids": [],
            "date_order": odoo.fields.Datetime.to_string(odoo.fields.Datetime.now()),
            **extra,
        }

    def test_create_path_rejects_client_supplied_access_token(self):
        """`access_token` is the sole credential of the public
        /pos/ticket/validate route, which redirects to the customer's portal
        invoice. `_ensure_access_token` keeps any value already set, so a
        client-supplied token used to be persisted verbatim — downgrading a
        server-side uuid4 (os.urandom) to the UI's Math.random. The update path
        already popped it; the create path did not."""
        self.open_new_session()
        uuid = "11111111-1111-4111-8111-111111111111"
        attacker_token = "predictable-token-from-math-random"

        self.env["pos.order"].sync_from_ui(
            [self._base_order_vals(self.pos_session, uuid, access_token=attacker_token)]
        )
        order = self.env["pos.order"].search([("uuid", "=", uuid)])

        self.assertTrue(order, "order was not created")
        self.assertNotEqual(
            order.access_token,
            attacker_token,
            "server persisted a client-supplied access_token",
        )
        self.assertTrue(order.access_token, "server did not mint an access_token")

    def test_update_path_still_rejects_client_supplied_access_token(self):
        """The pre-existing strip on the update path must keep working, and a
        second sync must not be able to rotate the token to a chosen value."""
        self.open_new_session()
        uuid = "22222222-2222-4222-8222-222222222222"

        self.env["pos.order"].sync_from_ui(
            [self._base_order_vals(self.pos_session, uuid)]
        )
        order = self.env["pos.order"].search([("uuid", "=", uuid)])
        minted = order.access_token

        self.env["pos.order"].sync_from_ui(
            [
                self._base_order_vals(
                    self.pos_session,
                    uuid,
                    id=order.id,
                    access_token="second-attempt-token",
                )
            ]
        )
        self.assertEqual(
            self.env["pos.order"].search([("uuid", "=", uuid)]).access_token,
            minted,
            "client rotated the access_token through the update path",
        )


@odoo.tests.tagged("post_install", "-at_install")
class TestAudit4TaxIsUsed(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def test_is_used_query_runs_under_psycopg3(self):
        """`_hook_compute_is_used` marks a tax referenced by any pos.order.line
        as used. Its query passed a tuple to `IN %s`, which psycopg3 (this fork)
        adapts as a composite row rather than an IN-list, so it raised
        `syntax error at or near "$1"`. That aborted the `is_used` compute for
        every tax, which broke TestPoSCommon.setUpClass (_create_taxes) and with
        it the whole point_of_sale Python suite. Use `= ANY(%s)` over a list."""
        self.open_new_session()
        product = self.create_product(
            "TaxUsedProd", self.categ_basic, 100, tax_ids=self.taxes["tax7"].ids
        )
        order = self.create_ui_order_data([(product, 1)])
        self.env["pos.order"].sync_from_ui([order])

        # Reading the computed field runs the overridden hook; pre-fix this
        # raised psycopg.errors.SyntaxError.
        self.assertTrue(
            self.taxes["tax7"].is_used,
            "a tax carried by a pos.order.line must count as used",
        )
