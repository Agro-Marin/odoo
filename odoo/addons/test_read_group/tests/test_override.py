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
                many2one_field.comodel_name = Model._name
                with self.subTest(model=Model._name):
                    try:
                        Order._read_group([], ["many2one_id"], order="many2one_id")
                    except GroupingError:
                        self.fail(
                            f"Bad method override for model {Model._name}. "
                            "Fields used by both customized order and Model._order "
                            "must be added to the query.groupby when query.groupby "
                            "is not empty to avoid GroupingError."
                        )
                    except Exception as e:
                        self.fail(
                            f"Unexpected {type(e).__name__} for model "
                            f"{Model._name} while checking order override "
                            f"compatibility: {e}"
                        )

    def test_order_by_m2o_chaining_to_id_ordered_comodel(self):
        Partner = self.env.registry["res.partner"]
        Country = self.env.registry["res.country"]
        self.addCleanup(setattr, Partner, "_order", Partner._order)
        self.addCleanup(setattr, Country, "_order", Country._order)
        Partner._order = "country_id, id"
        Country._order = "id"
        result = self.env["res.users"]._read_group(
            [], ["partner_id"], ["__count"], order="partner_id"
        )
        partners = self.env["res.partner"].concat(*(p for p, _count in result if p))
        expected_order = partners.sorted(
            key=lambda p: (p.country_id.id or float("inf"), p.id)
        )
        self.assertEqual(
            list(partners),
            list(expected_order),
            "partner_id groups must be ordered by the chained "
            "country_id, id comodel order",
        )
