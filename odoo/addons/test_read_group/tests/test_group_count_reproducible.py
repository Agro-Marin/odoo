import random

from odoo.orm.domain import Domain
from odoo.tests.common import TransactionCase


class TestGroupCountReproducible(TransactionCase):
    SEED = 20260727
    GROUPINGS = 120

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]
        cls.Aggregate = cls.env["test_read_group.aggregate"]
        cls.partners = cls.Partner.create(
            [
                {"name": "gc-null"},
                {"name": "gc-empty-a"},
                {"name": "gc-empty-b"},
                {"name": "gc-ref-a", "ref": "a", "comment": "c1"},
                {"name": "gc-ref-a2", "ref": "a"},
                {"name": "gc-ref-b", "ref": "b", "comment": "c1", "type": "invoice"},
            ]
        )
        cls.env.flush_all()
        cls.env.cr.execute(
            "UPDATE res_partner SET ref = '', comment = '' WHERE id = ANY(%s)",
            [cls.partners[1:3].ids],
        )
        cls.records = cls.Aggregate.create(
            [
                {"key": key, "value": value, "partner_id": partner.id}
                for key, value, partner in [
                    (1, 10, cls.partners[0]),
                    (1, 20, cls.partners[1]),
                    (2, 10, cls.partners[2]),
                    (2, 0, cls.partners[3]),
                    (3, 0, cls.partners[4]),
                    (3, 30, cls.partners[5]),
                ]
            ]
        )
        cls.env.flush_all()
        cls.env.invalidate_all()

    def _assert_groups_reproduce(self, model, base_domain, groupby):
        rows = model.formatted_read_group(base_domain, groupby, ["__count"])
        summed = 0
        for row in rows:
            extra = row.get("__extra_domain") or []
            scoped = Domain(base_domain) & Domain(extra)
            reopened = model.search_count(scoped)
            key = {k: v for k, v in row.items() if not k.startswith("__")}
            self.assertEqual(
                reopened,
                row["__count"],
                f"group {key} of {groupby!r} reports {row['__count']} records "
                f"but its own domain {list(scoped)!r} selects {reopened}",
            )
            summed += row["__count"]
        self.assertEqual(
            summed,
            model.search_count(base_domain),
            f"groups of {groupby!r} do not tile the record set",
        )

    def test_empty_string_and_null_form_one_reproducible_group(self):
        model = self.Partner.with_context(active_test=False)
        base = Domain("id", "in", self.partners.ids)
        for fname in ("ref", "comment"):
            with self.subTest(field=fname):
                rows = model.formatted_read_group(base, [fname], ["__count"])
                empty = [row for row in rows if not row[fname]]
                self.assertEqual(
                    len(empty),
                    1,
                    f"NULL and '' must form ONE {fname} group, got "
                    f"{[row[fname] for row in rows]}",
                )
                self._assert_groups_reproduce(model, base, [fname])

    def test_generated_groupings_reproduce_their_counts(self):
        rng = random.Random(self.SEED)
        partner_specs = [
            "ref",
            "comment",
            "type",
            "active",
            "company_id",
            "create_date:day",
            "create_date:month",
            "create_date:year_number",
        ]
        aggregate_specs = ["key", "value", "partner_id", "partner_id.ref"]
        cases = [
            (
                self.Partner.with_context(active_test=False),
                Domain("id", "in", self.partners.ids),
                partner_specs,
            ),
            (
                self.Aggregate.with_context(active_test=False),
                Domain("id", "in", self.records.ids),
                aggregate_specs,
            ),
        ]
        for index in range(self.GROUPINGS):
            model, base, specs = cases[index % len(cases)]
            groupby = [rng.choice(specs)]
            if rng.random() < 0.3:
                groupby.append(rng.choice(specs))
            with self.subTest(index=index, model=model._name, groupby=groupby):
                self._assert_groups_reproduce(model, base, groupby)
