from freezegun import freeze_time

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from odoo.addons.http_routing.tests.common import MockRequest
from odoo.addons.loyalty.controllers.portal import CustomerPortalLoyalty

# 02:00 UTC is 20:00 of the previous day in Mexico City, so the two calendars
# disagree for the last six hours of every local day. Both tests below run inside
# that window: it is the only time a UTC `today()` and the user's own date differ,
# and it is ordinary working time here.
UTC_INSTANT = "2026-06-15 02:00:00"
LOCAL_DATE = "2026-06-14"
TZ = "America/Mexico_City"


@tagged("post_install", "-at_install")
class TestLoyaltyLocalDate(TransactionCase):
    """Date-only decisions taken on the user's calendar, not the server's."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_currency = cls.env.company.currency_id
        cls.other_currency = (
            cls.env["res.currency"]
            .with_context(active_test=False)
            .search([("id", "!=", cls.company_currency.id)], limit=1)
        )
        cls.other_currency.active = True
        cls.other_currency.rate_ids.unlink()
        # `currency_id` is readonly on res.currency.rate, so the rows are created
        # through the inverse rather than with an explicit currency in the values.
        cls.other_currency.write(
            {
                "rate_ids": [
                    Command.create(
                        {
                            "name": LOCAL_DATE,
                            "company_id": cls.env.company.id,
                            "rate": 2.0,
                        }
                    ),
                    Command.create(
                        {
                            "name": "2026-06-15",
                            "company_id": cls.env.company.id,
                            "rate": 4.0,
                        }
                    ),
                ],
            }
        )

    def test_rule_minimum_converts_at_the_users_calendar_date(self):
        """The rule minimum is a business threshold, so it uses the buyer's day.

        The rate doubles overnight, so reading the wrong calendar day doubles the
        amount an order has to reach before the promotion applies.
        """
        program = self.env["loyalty.program"].create(
            {
                "name": "Minimum",
                "program_type": "promotion",
                "rule_ids": [Command.create({"minimum_amount": 100})],
                "reward_ids": [Command.create({})],
            }
        )
        rule = program.rule_ids.with_context(tz=TZ)

        with freeze_time(UTC_INSTANT):
            self.assertEqual(fields.Date.today().isoformat(), "2026-06-15")
            self.assertEqual(rule._compute_amount(self.other_currency), 200.0)

    def test_portal_home_keeps_a_card_that_still_has_the_day_to_run(self):
        """A card expiring today is still money to its holder until local midnight."""
        user = new_test_user(
            self.env,
            login="loyalty_portal_tz",
            groups="base.group_portal",
            tz=TZ,
        )
        program = self.env["loyalty.program"].create(
            {"name": "Wallet", "program_type": "ewallet"}
        )
        card = self.env["loyalty.card"].create(
            {
                "program_id": program.id,
                "partner_id": user.partner_id.id,
                "points": 10,
                "expiration_date": LOCAL_DATE,
            }
        )

        user_env = self.env(user=user, context=dict(self.env.context, tz=TZ))
        with freeze_time(UTC_INSTANT), MockRequest(user_env, path="/my"):
            values = CustomerPortalLoyalty()._prepare_home_portal_values([])

        self.assertEqual(values["cards_per_programs"].get(program), card)
