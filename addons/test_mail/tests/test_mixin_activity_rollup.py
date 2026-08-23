import itertools

from odoo.tests import TransactionCase, tagged

STATES = ("overdue", "today", "planned", False)


@tagged("mail_activity")
class TestActivityStateRollup(TransactionCase):
    """A parent summarising its children's activity_state."""

    def _combinations(self):
        for size in range(len(STATES) + 1):
            yield from itertools.combinations_with_replacement(STATES, size)

    def test_it_agrees_with_the_alphabetical_sort_it_replaced(self):
        # fleet spelled this `sorted(states)[0]`, which is right only because
        # "overdue" happens to sort before "today". Renaming either value would
        # have silently inverted it.
        mixin = self.env["mixin.mail.activity"]
        for combo in self._combinations():
            present = {state for state in combo if state and state != "planned"}
            self.assertEqual(
                mixin._most_urgent_activity_state(
                    combo, among=("overdue", "today"), fallback="none"
                ),
                min(present) if present else "none",
            )

    def test_among_keeps_a_value_the_caller_cannot_store(self):
        # fleet.vehicle and stock.lot both offer only none/overdue/today, so
        # "planned" must not come back even when a child is planned.
        mixin = self.env["mixin.mail.activity"]
        self.assertEqual(
            mixin._most_urgent_activity_state(
                ["planned"], among=("overdue", "today"), fallback="none"
            ),
            "none",
        )

    def test_the_default_order_is_most_urgent_first(self):
        mixin = self.env["mixin.mail.activity"]
        self.assertEqual(
            mixin._most_urgent_activity_state(["planned", "today", "overdue"]),
            "overdue",
        )
        self.assertEqual(
            mixin._most_urgent_activity_state(["planned", "today"]), "today"
        )
        self.assertEqual(mixin._most_urgent_activity_state(["planned"]), "planned")
        self.assertIs(mixin._most_urgent_activity_state([]), False)
