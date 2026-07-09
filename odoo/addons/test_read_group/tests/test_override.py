from psycopg.errors import GroupingError

from odoo import models
from odoo.tests.common import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestReadGroupOverride(TransactionCase):
    def test_order_for_groupby(self):
        Order = self.env["test_read_group.order"]
        many2one_field = Order._fields["many2one_id"]
        self.addCleanup(
            setattr, many2one_field, "comodel_name", many2one_field.comodel_name
        )
        BaseModel = models.BaseModel
        for Model in self.env.registry.values():
            if (
                not Model._abstract
                and Model._auto
                and (
                    Model._order_field_to_sql is not BaseModel._order_field_to_sql
                    or Model._order_to_sql is not BaseModel._order_to_sql
                    or Model._read_group_orderby is not BaseModel._read_group_orderby
                )
            ):
                # methods for customized order are overridden by Model
                # change comodel_name of a many2one field as a hack for the test
                many2one_field.comodel_name = Model._name
                try:
                    Order._read_group([], ["many2one_id"], order="many2one_id")
                except GroupingError as e:
                    self.assertEqual(
                        e,
                        None,
                        f"Bad method override for model {Model._name}. "
                        "Fields used by both customized order and Model._order "
                        "must be added to the query.groupby when query.groupby "
                        "is not empty to avoid GroupingError.",
                    )

    def test_order_by_m2o_chaining_to_id_ordered_comodel(self):
        """Grouped read ordered by a many2one whose comodel ``_order`` chains
        through another many2one to an ``id``-ordered model must not raise
        GroupingError 42803.

        The chained column (here ``country_id`` of the ordered-by
        ``partner_id``) is not part of the GROUP BY, so ``_order_field_to_sql``
        must wrap it in ``ANY_VALUE()`` in its ``coorder == "id"`` branch rather
        than emit it bare into ORDER BY.
        """
        Partner = self.env.registry["res.partner"]
        Country = self.env.registry["res.country"]
        self.addCleanup(setattr, Partner, "_order", Partner._order)
        self.addCleanup(setattr, Country, "_order", Country._order)
        Partner._order = "country_id, id"
        Country._order = "id"
        # Must not raise GroupingError (empty table still triggers plan-time 42803).
        self.env["res.users"]._read_group(
            [], ["partner_id"], ["__count"], order="partner_id"
        )
