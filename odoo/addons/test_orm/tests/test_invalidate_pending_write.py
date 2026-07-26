"""Field-scoped invalidation must not orphan a pending write.

The cache holds an invariant: a field marked *dirty* for a record has a value in
``_data`` for that record, because that value is what the next flush writes.
``FieldCache.invalidate_all`` (the transaction-wide path behind
``env.invalidate_all(flush=False)``) upholds it explicitly — it keeps every
dirty entry.  The field-scoped path (``invalidate_model`` /
``invalidate_recordset`` with ``flush=False``) did not: it dropped the value and
left the flag, so at the next flush the record was either

* re-fetched from the database and written straight back — the pending write
  silently reverted, no error anywhere — or
* missing from the cache — opaque ``RuntimeError: Could not find all values of
  ... to flush them``.

Both are unrecoverable at that point, so the guard refuses up front.

NOTE these tests deliberately do NOT use ``assertRaises``: the ORM test suite's
override opens a savepoint, which flushes, which drains the very dirty set under
test.  ``_assert_refuses`` calls the operation directly instead.
"""

from odoo.tests.common import TransactionCase


class TestInvalidatePendingWrite(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]

    def _dirty_record(self):
        """Return a record with a pending (unflushed) write on ``ref``."""
        record = self.Partner.create({"name": "orig", "ref": "R0"})
        self.env.flush_all()
        record.write({"ref": "R1"})
        self.assertTrue(
            self.env._core.get_dirty(self.Partner._fields["ref"]),
            "precondition: the write must leave 'ref' dirty",
        )
        return record

    def _assert_refuses(self, func, *args, **kwargs):
        """Assert ``func`` raises ValueError, without flushing beforehand."""
        try:
            func(*args, **kwargs)
        except ValueError as exc:
            self.assertIn("pending write", str(exc))
            return
        self.fail("invalidation with flush=False accepted a pending write")

    def test_invalidate_recordset_refuses_pending_write(self):
        record = self._dirty_record()
        self._assert_refuses(record.invalidate_recordset, ["ref"], flush=False)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(record.ref, "R1")

    def test_invalidate_model_refuses_pending_write(self):
        record = self._dirty_record()
        self._assert_refuses(self.Partner.invalidate_model, ["ref"], flush=False)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(record.ref, "R1")

    def test_invalidate_all_fields_refuses_pending_write(self):
        """``fnames=None`` (every field of the model) is guarded too."""
        record = self._dirty_record()
        self._assert_refuses(record.invalidate_recordset, flush=False)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(record.ref, "R1")

    def test_invalidate_other_records_is_allowed(self):
        """Only records that actually carry the pending write are refused."""
        clean = self.Partner.create({"name": "clean", "ref": "C0"})
        dirty = self._dirty_record()
        clean.invalidate_recordset(["ref"], flush=False)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(dirty.ref, "R1")

    def test_invalidate_other_fields_is_allowed(self):
        record = self._dirty_record()
        record.invalidate_recordset(["name"], flush=False)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(record.ref, "R1")

    def test_flush_true_stays_the_normal_path(self):
        """The default (``flush=True``) drains the dirty set first, so it never
        trips the guard and the write survives.
        """
        record = self._dirty_record()
        record.invalidate_recordset(["ref"])
        self.assertEqual(record.ref, "R1")

    def test_transaction_wide_invalidate_all_keeps_pending_writes(self):
        """The invariant the field-scoped path now matches."""
        record = self._dirty_record()
        self.env.invalidate_all(flush=False)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(record.ref, "R1")
