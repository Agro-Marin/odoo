from unittest.mock import patch

from odoo.orm.models.mixins._cache_scan import (
    can_scan_identity,
    can_scan_read,
    can_scan_sorted,
    can_scan_truthy,
)
from odoo.tests import TransactionCase


class CacheScanEquivalenceCase(TransactionCase):
    """Every fast path must answer what the slow path answers.

    ``mapped``, ``filtered``, ``grouped``, ``sorted`` and ``read`` each read the
    raw field cache when the field's ``cache_*`` flags allow it. The flags are
    checked against the converters in ``orm/tests/test_cache_scan_allowlists``;
    what is checked here is the other end -- that the scans built on them agree
    with going through the descriptor, on real records with real values.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.records = cls.env["test_orm.mixed"].create(
            [
                {
                    "foo": "b",
                    "text": "zz",
                    "truth": True,
                    "count": 3,
                    "number": 1.5,
                    "date": "2020-01-02",
                    "moment": "2020-01-02 03:04:05",
                },
                {
                    "foo": "a",
                    "text": "",
                    "truth": False,
                    "count": 0,
                    "number": 0.0,
                },
                {
                    "foo": "",
                    "truth": True,
                    "count": -1,
                    "number": 2.5,
                    "date": "2019-06-06",
                },
            ]
        )
        cls.env.flush_all()

    def _scannable(self, predicate):
        model = self.env["test_orm.mixed"]
        return [
            name
            for name, field in model._fields.items()
            if field.store and predicate(field) and name != "id"
        ]

    def test_the_fixture_exercises_several_types(self):
        scannable = set(self._scannable(can_scan_identity))
        types = {self.env["test_orm.mixed"]._fields[n].type for n in scannable}
        self.assertGreaterEqual(
            len(types),
            5,
            f"test_orm.mixed only offers {sorted(types)} to scan; the "
            f"equivalence assertions below are thinner than they look",
        )

    def test_mapped_agrees_with_reading_each_record(self):
        for name in self._scannable(can_scan_identity):
            with self.subTest(field=name):
                self.env.invalidate_all()
                self.records.fetch([name])
                fast = self.records.mapped(name)
                self.env.invalidate_all()
                slow = [record[name] for record in self.records]
                self.assertEqual(fast, slow)

    def test_filtered_agrees_with_a_lambda(self):
        for name in self._scannable(can_scan_truthy):
            with self.subTest(field=name):
                self.env.invalidate_all()
                self.records.fetch([name])
                fast = self.records.filtered(name)
                self.env.invalidate_all()
                slow = self.records.filtered(lambda r, n=name: r[n])
                self.assertEqual(fast, slow)

    def test_grouped_agrees_with_a_lambda(self):
        for name in self._scannable(can_scan_identity):
            with self.subTest(field=name):
                self.env.invalidate_all()
                self.records.fetch([name])
                fast = {k: v.ids for k, v in self.records.grouped(name).items()}
                self.env.invalidate_all()
                slow = {
                    k: v.ids
                    for k, v in self.records.grouped(lambda r, n=name: r[n]).items()
                }
                self.assertEqual(fast, slow)

    def test_sorted_agrees_with_the_comparator_path(self):
        # Against the ORM's own slow path, not against Python's sorted():
        # an in-memory sort deliberately reproduces PostgreSQL's null ordering
        # (ASC NULLS LAST), which Python's sorted() does not, and re-deriving
        # that rule here would only assert the test against itself.
        for name in self._scannable(can_scan_sorted):
            for order in (name, f"{name} desc"):
                with self.subTest(order=order):
                    self.env.invalidate_all()
                    self.records.fetch([name])
                    fast = self.records.sorted(order).ids
                    self.env.invalidate_all()
                    self.records.fetch([name])
                    with patch(
                        "odoo.orm.models.mixins.traversal.can_scan_sorted",
                        return_value=False,
                    ):
                        slow = self.records.sorted(order).ids
                    self.assertEqual(fast, slow, f"sorted({order!r}) diverges")

    def test_read_agrees_with_the_record_branch(self):
        names = self._scannable(can_scan_read)
        self.env.invalidate_all()
        fast = self.records.read(names)
        self.env.invalidate_all()
        with patch("odoo.orm.models.mixins.read.can_scan_read", return_value=False):
            slow = self.records.read(names)
        self.assertEqual(fast, slow)

    def test_a_boolean_is_deliberately_not_sorted_from_the_cache(self):
        # sort_ids_by_cache groups falsy values with NULL to reproduce
        # PostgreSQL's null ordering. For every other scannable type the falsy
        # value is the null; for a Boolean, False is a value, so the cache sort
        # puts it where NULL belongs. Pinned because the exclusion looks
        # arbitrary next to the other types and is not.
        field = self.env["test_orm.mixed"]._fields["truth"]
        self.assertFalse(
            can_scan_sorted(field),
            "a boolean must not be sorted from the cache; see "
            "fields/misc.py Boolean.cache_is_orderable",
        )
        self.env.invalidate_all()
        self.records.fetch(["truth"])
        self.assertEqual(
            self.records.sorted("truth").ids,
            self.records.sorted(lambda r: r.truth).ids,
        )


class PropertiesAreNotTruthinessPreservingCase(TransactionCase):
    """The converse of the flag: these two really do break it.

    Pinned so nobody restores ``cache_truthiness_matches`` on either class
    after reading only the type name.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env.user
        cls.with_definition = cls.env["test_orm.discussion"].create(
            {
                "name": "defined",
                "participants": [(4, cls.user.id)],
                "attributes_definition": [{"name": "a", "type": "char", "string": "A"}],
            }
        )
        cls.without_definition = cls.env["test_orm.discussion"].create(
            {
                "name": "undefined",
                "participants": [(4, cls.user.id)],
                "attributes_definition": [],
            }
        )
        cls.env.flush_all()

    def test_properties_truthiness_does_not_follow_the_cache(self):
        message = self.env["test_orm.message"].create(
            {
                "name": "m",
                "discussion": self.without_definition.id,
                "author": self.user.id,
            }
        )
        self.env.flush_all()
        field = message._fields["attributes"]
        self.assertFalse(
            field.cache_truthiness_matches,
            "Property.__len__ counts the *definition*, not the cached values",
        )
        # values orphaned by a definition that was emptied: truthy in the cache,
        # falsy as a record value
        field._get_cache(self.env)[message.id] = {"ghost": 1}
        self.assertTrue(bool(field._get_cache(self.env)[message.id]))
        self.assertFalse(bool(message.attributes))
        self.assertEqual(
            message.filtered("attributes"),
            message.filtered(lambda r: r.attributes),
        )

    def test_properties_definition_truthiness_does_not_follow_the_cache(self):
        field = self.with_definition._fields["attributes_definition"]
        self.assertFalse(
            field.cache_truthiness_matches,
            "convert_to_record drops entries whose name or type is falsy",
        )
        field._get_cache(self.env)[self.with_definition.id] = [{"name": "a"}]
        self.assertTrue(bool(field._get_cache(self.env)[self.with_definition.id]))
        self.assertFalse(bool(self.with_definition.attributes_definition))
        self.assertEqual(
            self.with_definition.filtered("attributes_definition"),
            self.with_definition.filtered(lambda r: r.attributes_definition),
        )
