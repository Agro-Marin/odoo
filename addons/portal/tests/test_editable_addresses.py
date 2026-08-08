"""``/my/addresses`` must answer "which of these may I edit" once, not per card.

``portal.address_list`` asked the singleton predicate inside its ``t-foreach``,
so every address rendered cost a ``search_count`` plus the record-rule machinery
around it — a page whose query count grew with the customer's address book.

The batch primitive has to give exactly the same answer as the predicate it
replaces, including for the addresses that must *not* be editable, so both
halves are asserted here: the permission semantics, and the cost.
"""

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestEditableAddresses(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.company_partner = Partner.create(
            {"name": "Editable Co", "is_company": True}
        )
        cls.customer = Partner.create(
            {"name": "Editable Customer", "parent_id": cls.company_partner.id}
        )
        cls.user = cls.env["res.users"].create(
            {
                "login": "editable_addresses",
                "password": "editable_addresses",
                "partner_id": cls.customer.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
            }
        )
        cls.own_addresses = Partner.create(
            [
                {
                    "name": f"Delivery {index}",
                    "parent_id": cls.company_partner.id,
                    "type": "delivery",
                }
                for index in range(10)
            ]
        )
        # A sibling contact of the same company: a person, not an address. The
        # rule deliberately excludes type "contact" so a customer cannot edit a
        # colleague's record.
        cls.colleague = Partner.create(
            {
                "name": "Colleague",
                "parent_id": cls.company_partner.id,
                "type": "contact",
            }
        )
        # Someone else's address entirely.
        cls.foreign_address = Partner.create({"name": "Foreign", "type": "delivery"})

    def _as_user(self, records):
        return records.with_user(self.user).with_context(active_test=False)

    def test_batch_matches_the_singleton_predicate(self):
        candidates = (
            self.customer
            | self.own_addresses
            | self.colleague
            | self.foreign_address
            | self.company_partner
        )

        batched = self._as_user(candidates)._filter_editable_by_current_customer()
        one_by_one = candidates.browse(
            [
                partner.id
                for partner in self._as_user(candidates)
                if partner._can_be_edited_by_current_customer()
            ]
        )

        self.assertEqual(batched, one_by_one)

    def test_permission_semantics(self):
        editable = self._as_user(
            self.customer | self.own_addresses | self.colleague | self.foreign_address
        )._filter_editable_by_current_customer()

        self.assertIn(self.customer, editable, "own partner is always editable")
        self.assertEqual(
            self.own_addresses, editable - self.customer, "company addresses"
        )
        self.assertNotIn(self.colleague, editable, "a contact is not an address")
        self.assertNotIn(self.foreign_address, editable, "another tree entirely")

    def _query_count(self, call):
        """Queries issued by ``call``, after a warm-up run.

        The warm-up removes the one-off costs that are not what this measures:
        record-rule compilation, field metadata, the current-partner lookup. What
        is left is the work the method does *every* time it runs.
        """
        call()
        before = self.env.cr.sql_log_count
        call()
        return self.env.cr.sql_log_count - before

    def test_batch_cost_does_not_grow_with_the_address_book(self):
        """The property that matters is the shape of the curve, not a constant.

        A page cost is only a bug when it scales: the singleton predicate asked
        one ``search_count`` per address, so `/my/addresses` grew a query for
        every address a customer added. The batch primitive must answer a set of
        any size for the same price.
        """
        two = self._as_user(self.own_addresses[:2])
        ten = self._as_user(self.own_addresses[:10])

        cost_two = self._query_count(two._filter_editable_by_current_customer)
        cost_ten = self._query_count(ten._filter_editable_by_current_customer)

        self.assertEqual(cost_two, cost_ten, "cost scales with the set size")

    def test_batch_is_cheaper_than_asking_once_per_address(self):
        addresses = self._as_user(self.own_addresses)

        batched = self._query_count(addresses._filter_editable_by_current_customer)
        one_by_one = self._query_count(
            lambda: [
                partner._can_be_edited_by_current_customer() for partner in addresses
            ]
        )

        self.assertLess(batched, one_by_one)

    def test_empty_recordset_asks_nothing(self):
        empty = self.env["res.partner"].with_user(self.user)

        with self.assertQueryCount(0):
            self.assertFalse(empty._filter_editable_by_current_customer())
