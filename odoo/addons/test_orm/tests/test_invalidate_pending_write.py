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


class TestFnameResolution(TransactionCase):
    """An unknown field name names the field *and* the model, on every entry point.

    ``invalidate_model`` / ``invalidate_recordset`` already raised a ``ValueError``
    saying both; the flush and recompute siblings indexed ``self._fields`` raw and
    surfaced a bare ``KeyError('bogus')`` — same caller mistake, same object, two
    unrelated exception types and one of them naming neither the model nor the API
    that rejected it.  ``helpers.resolve_fnames`` is now the single resolver.
    """

    def setUp(self):
        super().setUp()
        self.record = self.env["res.partner"].create({"name": "x"})

    def _assert_names_field_and_model(self, func, *args):
        with self.assertRaises(ValueError) as ctx:
            func(*args)
        message = str(ctx.exception)
        self.assertIn("bogus", message)
        self.assertIn("res.partner", message)

    def test_flush_model(self):
        self._assert_names_field_and_model(
            self.env["res.partner"].flush_model, ["bogus"]
        )

    def test_flush_recordset(self):
        self._assert_names_field_and_model(self.record.flush_recordset, ["bogus"])

    def test_recompute_model(self):
        self._assert_names_field_and_model(
            self.env["res.partner"]._recompute_model, ["bogus"]
        )

    def test_recompute_recordset(self):
        self._assert_names_field_and_model(self.record._recompute_recordset, ["bogus"])

    def test_invalidate_recordset_unchanged(self):
        self._assert_names_field_and_model(self.record.invalidate_recordset, ["bogus"])

    def test_invalidate_model_unchanged(self):
        self._assert_names_field_and_model(
            self.env["res.partner"].invalidate_model, ["bogus"]
        )

    def test_valid_names_still_pass(self):
        self.record.write({"ref": "R"})
        self.record.flush_recordset(["ref"])
        self.env["res.partner"].flush_model(["ref"])
        self.record._recompute_recordset(["display_name"])
        self.env["res.partner"]._recompute_model(["display_name"])


class TestInvalidateInversePendingWrite(TransactionCase):
    """The inverse-field pass must not drop a pending write either.

    ``_invalidate_cache`` also invalidates the *inverse* of every field it was
    asked to invalidate, across all ids — a consistency side effect the caller
    never requested, and one the ``flush=False`` guard does not cover (it scans
    only the requested fields).  Invalidating a one2many therefore used to wipe
    the counterpart many2one on every record, dirty ones included: the flag
    survived, the value did not, and the next flush re-read the database value
    and wrote it straight back.  The write vanished with no error.

    ``account_full_reconcile`` and ``account_move_send`` both invalidate a
    one2many with ``flush=False``, so this was reachable from stock addons.
    """

    def _dirty_inverse(self):
        """Return ``(bank, target_partner)`` with a pending write on the
        many2one that is the inverse of ``res.partner.bank_ids``."""
        source = self.env["res.partner"].create({"name": "source"})
        target = self.env["res.partner"].create({"name": "target"})
        bank = self.env["res.partner.bank"].create(
            {"acc_number": "ACC-1", "partner_id": source.id}
        )
        self.env.flush_all()
        self.env.invalidate_all()

        bank.write({"partner_id": target.id})
        field = self.env["res.partner.bank"]._fields["partner_id"]
        self.assertIn(
            bank.id,
            self.env._core.get_dirty(field) or (),
            "precondition: the write must leave 'partner_id' dirty",
        )
        return source, bank, target

    def test_inverse_invalidation_keeps_the_pending_write(self):
        source, bank, target = self._dirty_inverse()
        source.invalidate_recordset(["bank_ids"], flush=False)

        field = self.env["res.partner.bank"]._fields["partner_id"]
        self.assertIn(
            bank.id,
            field._get_cache(self.env),
            "the dirty value must survive the inverse-field invalidation",
        )

        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(bank.partner_id, target)

    def test_inverse_invalidation_still_drops_clean_values(self):
        """Only the dirty ids are spared; the rest is invalidated as before."""
        source = self.env["res.partner"].create({"name": "source"})
        target = self.env["res.partner"].create({"name": "target"})
        Bank = self.env["res.partner.bank"]
        bank = Bank.create({"acc_number": "ACC-1", "partner_id": source.id})
        clean = Bank.create({"acc_number": "ACC-2", "partner_id": source.id})
        self.env.flush_all()
        self.env.invalidate_all()

        field = Bank._fields["partner_id"]
        clean.partner_id  # noqa: B018 - populate the cache
        bank.write({"partner_id": target.id})
        cache = field._get_cache(self.env)
        self.assertIn(bank.id, cache)
        self.assertIn(clean.id, cache)

        source.invalidate_recordset(["bank_ids"], flush=False)

        cache = field._get_cache(self.env)
        self.assertIn(bank.id, cache)
        self.assertNotIn(clean.id, cache)

    def test_invalidate_model_inverse_keeps_the_pending_write(self):
        _source, bank, target = self._dirty_inverse()
        self.env["res.partner"].invalidate_model(["bank_ids"], flush=False)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(bank.partner_id, target)
