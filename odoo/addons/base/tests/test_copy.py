"""Contract of `CopyMixin.copy_data` / `CopyMixin.copy`.

`copy_data` returns a list positionally aligned with ``self``, and addon
overrides zip the two together and mutate the dicts in place. A `None` entry
(for a record this operation has already copied) breaks every one of those
overrides with a bare `TypeError`, so both ways of producing one are closed off:
a repeated record in ``self`` is rejected outright, and the one2many recursion
drops already-copied records before recursing into the child model.
"""

from collections import defaultdict

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCopyDataContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]

    def test_duplicated_recordset_is_refused_by_copy_data(self):
        """`copy()` would answer two occurrences with a single record and hand
        back a recordset shorter than ``self``, silently mispairing callers that
        zip the two together."""
        partner = self.Partner.create({"name": "Copy Contract"})
        twice = self.Partner.browse([partner.id, partner.id])
        self.assertEqual(len(twice), 2)

        with self.assertRaises(ValueError) as capture:
            twice.copy_data()
        self.assertIn("more than once", str(capture.exception))

        with self.assertRaises(ValueError):
            twice.copy()

    def test_deduplicated_recordset_copies_normally(self):
        partner = self.Partner.create({"name": "Copy Contract Dedup"})
        copies = self.Partner.browse([partner.id]).copy()
        self.assertEqual(len(copies), 1)
        self.assertNotEqual(copies, partner)

    def test_distinct_records_stay_paired_with_their_copies(self):
        """The property every `zip(self, copy_data(...))` override relies on."""
        partners = self.Partner.create(
            [{"name": "Copy Pair A"}, {"name": "Copy Pair B"}]
        )
        vals_list = partners.copy_data()
        self.assertEqual(len(vals_list), len(partners))
        self.assertTrue(all(vals is not None for vals in vals_list))
        for partner, vals in zip(partners, vals_list, strict=True):
            self.assertIn(partner.name, vals["name"])

    def _make_export(self, name):
        """`ir.exports.export_fields` is one of the few `copy=True` one2many
        fields in `base` (One2many defaults to copy=False), so it is what makes
        the recursion below observable at all."""
        return self.env["ir.exports"].create(
            {
                "name": name,
                "resource": "res.partner",
                "export_fields": [(0, 0, {"name": "name"})],
            }
        )

    def test_already_copied_o2m_lines_never_reach_the_child_copy_data(self):
        """An already-copied line used to be handed to the child model's
        `copy_data`, come back as `None`, and be dropped here -- passing through
        every override on the way. It is now filtered out before recursing.
        """
        export = self._make_export("Copy Export")
        line = export.export_fields
        self.assertTrue(line, "the fixture needs a copied one2many line")

        # Pretend the line was already copied earlier in this operation, which
        # is what a cycle or two overlapping copied relations produce.
        seen = defaultdict(set)
        seen["ir.exports.line"].add(line.id)

        received = []
        line_cls = type(self.env["ir.exports.line"])
        original = line_cls.copy_data

        def spy(records, default=None):
            received.append(tuple(records.ids))
            return original(records, default)

        self.patch(line_cls, "copy_data", spy)
        vals_list = export.with_context(__copy_data_seen=seen).copy_data()

        self.assertNotIn(
            (line.id,),
            received,
            "an already-copied line must not be passed to the child copy_data",
        )
        self.assertEqual(vals_list[0].get("export_fields", []), [])
        self.assertTrue(all(vals is not None for vals in vals_list))

    def test_normal_o2m_lines_are_still_copied(self):
        export = self._make_export("Copy Export Kept")
        copy = export.copy()
        self.assertEqual(len(copy.export_fields), 1)
        self.assertEqual(copy.export_fields.name, "name")
        self.assertNotEqual(copy.export_fields, export.export_fields)
