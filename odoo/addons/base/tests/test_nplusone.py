from odoo.libs.profiling import nplusone
from odoo.orm.models.mixins import create as _create_mod
from odoo.orm.models.mixins import read as _read_mod
from odoo.orm.models.mixins import search as _search_mod
from odoo.orm.models.mixins import unlink as _unlink_mod
from odoo.orm.models.mixins import write as _write_mod
from odoo.tests.common import TransactionCase, tagged

_CRUD_MODS = (_create_mod, _write_mod, _unlink_mod, _search_mod, _read_mod)


@tagged("-standard", "nplusone")
class TestNplusOneDetection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_enabled = nplusone._n1_enabled
        nplusone._n1_enabled = True
        cls._original_crud_enabled = [m._n1_enabled for m in _CRUD_MODS]
        for _mod in _CRUD_MODS:
            _mod._n1_enabled = True
        cls._original_tracker = cls.env.transaction._n1_tracker
        cls.env.transaction._n1_tracker = nplusone.NplusOneTracker()

    @classmethod
    def tearDownClass(cls):
        nplusone._n1_enabled = cls._original_enabled
        for _mod, _orig in zip(_CRUD_MODS, cls._original_crud_enabled, strict=True):
            _mod._n1_enabled = _orig
        cls.env.transaction._n1_tracker = cls._original_tracker
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.tracker = self.env.transaction._n1_tracker
        self.tracker.clear()

    def test_write_n1_detected(self):
        categories = self.env["res.partner.tag"].create(
            [{"name": f"N1 Test Cat {i}"} for i in range(5)]
        )
        self.tracker.clear()

        for cat in categories:
            cat.write({"name": "Updated"})

        violations = [
            (key, entry)
            for key, entry in self.tracker._data.items()
            if entry.count >= nplusone.NplusOneTracker.THRESHOLD
            and key[0] == "write"
            and key[1] == "res.partner.tag"
        ]
        self.assertTrue(violations, "N+1 write pattern should be detected")
        entry = violations[0][1]
        self.assertEqual(entry.count, 5)
        self.assertEqual(entry.total_records, 5)
        self.assertEqual(len(entry.vals_fingerprints), 1, "Same fields every call")

    def test_batch_write_no_violation(self):
        categories = self.env["res.partner.tag"].create(
            [{"name": f"Batch Test Cat {i}"} for i in range(5)]
        )
        self.tracker.clear()

        categories.write({"name": "Batch Updated"})

        for entry in self.tracker._data.values():
            if entry.count >= nplusone.NplusOneTracker.THRESHOLD:
                self.fail("Batch write should not trigger N+1 detection")

    def test_create_n1_detected(self):
        self.tracker.clear()

        for i in range(5):
            self.env["res.partner.tag"].create({"name": f"N1 Cat {i}"})

        violations = [
            (key, entry)
            for key, entry in self.tracker._data.items()
            if entry.count >= nplusone.NplusOneTracker.THRESHOLD
            and key[0] == "create"
            and key[1] == "res.partner.tag"
        ]
        self.assertTrue(violations, "N+1 create pattern should be detected")
        self.assertEqual(violations[0][1].count, 5)

    def test_unlink_n1_detected(self):
        categories = self.env["res.partner.tag"].create(
            [{"name": f"Unlink Cat {i}"} for i in range(5)]
        )
        self.tracker.clear()

        for cat in categories:
            cat.unlink()

        violations = [
            (key, entry)
            for key, entry in self.tracker._data.items()
            if entry.count >= nplusone.NplusOneTracker.THRESHOLD and key[0] == "unlink"
        ]
        self.assertTrue(violations, "N+1 unlink pattern should be detected")

    def test_batch_create_no_violation(self):
        self.tracker.clear()

        self.env["res.partner.tag"].create(
            [{"name": f"Batch Cat {i}"} for i in range(20)]
        )

        for entry in self.tracker._data.values():
            if entry.count >= nplusone.NplusOneTracker.THRESHOLD:
                self.fail("Batch create should not trigger N+1 detection")

    def test_report_emits_warning(self):
        self.tracker.clear()

        for i in range(5):
            self.env["res.partner.tag"].create({"name": f"Report Cat {i}"})

        with self.assertLogs("odoo.orm.nplusone", level="WARNING") as log:
            self.tracker.report()

        self.assertTrue(
            any("N+1 detected" in msg for msg in log.output),
            "Report should emit N+1 warning",
        )
        self.assertTrue(
            any("res.partner.tag" in msg for msg in log.output),
            "Warning should mention the model name",
        )

    def test_different_fields_tracked(self):
        categories = self.env["res.partner.tag"].create(
            [{"name": f"FP Cat {i}"} for i in range(4)]
        )
        self.tracker.clear()

        for i, cat in enumerate(categories):
            if i % 2 == 0:
                cat.write({"name": "Even"})
            else:
                cat.write({"color": 1})

        violations = [
            (key, entry)
            for key, entry in self.tracker._data.items()
            if entry.count >= 2 and key[0] == "write"
        ]
        for _, entry in violations:
            self.assertLess(entry.count, nplusone.NplusOneTracker.THRESHOLD)


@tagged("-standard", "nplusone")
class TestNplusOneDisabled(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_enabled = nplusone._n1_enabled
        nplusone._n1_enabled = False

    @classmethod
    def tearDownClass(cls):
        nplusone._n1_enabled = cls._original_enabled
        super().tearDownClass()

    def test_no_tracker_when_disabled(self):
        self.assertFalse(nplusone._n1_enabled)
        cat = self.env["res.partner.tag"].create({"name": "Disabled Test"})
        cat.write({"name": "Updated"})
        cat.unlink()


@tagged("-standard", "nplusone")
class TestNplusOneReadDetection(TestNplusOneDetection):
    def _entries(self, operation, model_name):
        return [
            entry
            for key, entry in self.tracker._data.items()
            if key[0] == operation and key[1] == model_name
        ]

    def _violations(self, operation, model_name):
        return [
            entry
            for key, entry in self.tracker._data.items()
            if key[0] == operation
            and key[1] == model_name
            and self.tracker._is_violation(operation, entry)
        ]

    def test_search_per_record_is_reported(self):
        categories = self.env["res.partner.tag"].create(
            [{"name": f"Read N1 {i}"} for i in range(10)]
        )
        self.env.flush_all()
        self.tracker.clear()

        for category in categories:
            self.env["res.partner.tag"].search([("id", "=", category.id)])

        violations = self._violations("search", "res.partner.tag")
        self.assertTrue(
            violations,
            "a search per record is the N+1 the tracker exists to name; "
            f"recorded {self._entries('search', 'res.partner.tag')}",
        )
        self.assertEqual(violations[0].count, 10)
        self.assertEqual(violations[0].total_records, 10)

    def test_one_batched_search_is_not_reported(self):
        categories = self.env["res.partner.tag"].create(
            [{"name": f"Batched {i}"} for i in range(10)]
        )
        self.env.flush_all()
        self.tracker.clear()

        self.env["res.partner.tag"].search([("id", "in", categories.ids)])

        self.assertFalse(self._violations("search", "res.partner.tag"))

    def test_a_repeated_wide_search_is_not_an_n_plus_one(self):
        categories = self.env["res.partner.tag"].create(
            [{"name": f"Wide {i}"} for i in range(10)]
        )
        self.env.flush_all()
        self.tracker.clear()

        for _ in range(10):
            self.env["res.partner.tag"].search([("id", "in", categories.ids)])

        entries = self._entries("search", "res.partner.tag")
        self.assertTrue(entries, "the calls were recorded")
        self.assertGreaterEqual(entries[0].count, 10)
        self.assertFalse(
            self._violations("search", "res.partner.tag"),
            "10 calls returning 10 records each average 10 per call, well over "
            "READ_RECORDS_PER_CALL, so this is not an N+1",
        )

    def test_a_search_that_finds_nothing_still_counts(self):
        self.tracker.clear()
        for i in range(10):
            self.env["res.partner.tag"].search([("name", "=", f"absent-{i}")])
        self.assertTrue(
            self._violations("search", "res.partner.tag"),
            "a search per record that matches nothing is still a search per record",
        )
