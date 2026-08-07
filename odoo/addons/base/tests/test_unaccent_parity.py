from odoo.orm.domain import Domain
from odoo.tests.common import TransactionCase


class TestUnaccentParity(TransactionCase):
    CASES = [
        ("Ærøskøbing", "aeroskobing"),
        ("Straße GmbH", "strasse"),
        ("Łódź Sp.", "lodz"),
        ("Đakovo d.o.o.", "dakovo"),
        ("Œuvre SA", "oeuvre"),
        ("Þingvellir", "thingvellir"),
        ("½ Portion", " 1/2"),
        ("Copyright ©", "(c)"),
    ]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partners = cls.env["res.partner"].create(
            [{"name": name} for name, _ in cls.CASES]
        )
        cls.env.flush_all()

    def _assert_parity(self, domain):
        model = self.env["res.partner"].with_context(active_test=False)
        sql_ids = set(model.search(domain).ids) & set(self.partners.ids)
        mem_ids = set(self.partners.filtered_domain(domain).ids)
        self.assertEqual(
            sql_ids,
            mem_ids,
            f"{domain} disagrees: search()-only={sorted(sql_ids - mem_ids)} "
            f"filtered_domain()-only={sorted(mem_ids - sql_ids)}",
        )

    def test_unaccent_rules_match_postgresql(self):
        if not self.env.registry.has_unaccent:
            self.skipTest("unaccent extension not installed")
        for _name, comparand in self.CASES:
            with self.subTest(comparand=comparand):
                self._assert_parity(Domain("name", "ilike", comparand))
                self._assert_parity(Domain("name", "not ilike", comparand))

    def test_unaccent_is_folded_before_case(self):
        if not self.env.registry.has_unaccent:
            self.skipTest("unaccent extension not installed")
        record = self.env["res.partner"].create({"name": "₹ Rupee Store"})
        self.env.flush_all()
        model = self.env["res.partner"].with_context(active_test=False)
        for comparand in ("rs", "Rs", "RS"):
            with self.subTest(comparand=comparand):
                domain = Domain("name", "ilike", comparand)
                self.assertIn(record.id, model.search(domain).ids)
                self.assertIn(record.id, record.filtered_domain(domain).ids)

    def test_unaccent_python_matches_server_exactly(self):
        if not self.env.registry.has_unaccent:
            self.skipTest("unaccent extension not installed")
        unaccent_python = self.env.registry.unaccent_python
        chars = [chr(c) for c in range(0x20, 0x3000)]
        self.env.cr.execute(
            "SELECT c, unaccent(c) FROM unnest(%s::text[]) AS c", (chars,)
        )
        mismatches = [
            (char, expected, unaccent_python(char))
            for char, expected in self.env.cr.fetchall()
            if expected != unaccent_python(char)
        ]
        self.assertEqual(mismatches, [], "Python fold diverges from unaccent()")
