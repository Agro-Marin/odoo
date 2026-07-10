from contextlib import contextmanager
from datetime import datetime

import psycopg.errors

import odoo
from odoo.exceptions import UserError
from odoo.modules.registry import Registry
from odoo.tests import common
from odoo.tests.common import BaseCase
from odoo.tools.misc import mute_logger

ADMIN_USER_ID = common.ADMIN_USER_ID


@contextmanager
def environment():
    """Return an environment with a new cursor for the current database; the
    cursor is committed and closed after the context block.
    """
    registry = Registry(common.get_db_name())
    with registry.cursor() as cr:
        yield odoo.api.Environment(cr, ADMIN_USER_ID, {})


def drop_sequence(code):
    with environment() as env:
        seq = env["ir.sequence"].search([("code", "=", code)])
        seq.unlink()


class TestIrSequenceStandard(BaseCase):
    """A few tests for a 'Standard' (i.e. PostgreSQL) sequence."""

    def test_ir_sequence_create(self):
        """Try to create a sequence object."""
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type",
                    "name": "Test sequence",
                }
            )
            self.assertTrue(seq)

    def test_ir_sequence_number_next_zero(self):
        """A standard sequence with number_next=0 must not crash.

        PostgreSQL sequences are 1-based (default MINVALUE 1), so START/RESTART
        WITH 0 is rejected; the helpers floor the value to 1 (regression: it
        raised an unhandled InvalidParameterValue on create and on write).
        """
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_seq_zero",
                    "name": "Zero sequence",
                    "implementation": "standard",
                    "number_next": 0,
                }
            )
            self.assertTrue(seq)
            self.assertTrue(env["ir.sequence"].next_by_code("test_seq_zero"))
            # Writing 0 on an existing standard sequence must not crash either.
            seq.write({"number_next": 0})
            self.assertTrue(env["ir.sequence"].next_by_code("test_seq_zero"))
            seq.unlink()

    def test_ir_sequence_search(self):
        """Try a search."""
        with environment() as env:
            seqs = env["ir.sequence"].search([])
            self.assertTrue(seqs)

    def test_ir_sequence_draw(self):
        """Try to draw a number."""
        with environment() as env:
            n = env["ir.sequence"].next_by_code("test_sequence_type")
            self.assertTrue(n)

    def test_ir_sequence_draw_twice(self):
        """Try to draw a number from two transactions."""
        with environment() as env0:
            with environment() as env1:
                n0 = env0["ir.sequence"].next_by_code("test_sequence_type")
                self.assertTrue(n0)
                n1 = env1["ir.sequence"].next_by_code("test_sequence_type")
                self.assertTrue(n1)

    @classmethod
    def tearDownClass(cls):
        drop_sequence("test_sequence_type")


class TestIrSequenceNoGap(BaseCase):
    """Copy of the previous tests for a 'No gap' sequence."""

    def test_ir_sequence_create_no_gap(self):
        """Try to create a sequence object."""
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_2",
                    "name": "Test sequence",
                    "implementation": "no_gap",
                }
            )
            self.assertTrue(seq)

    def test_ir_sequence_draw_no_gap(self):
        """Try to draw a number."""
        with environment() as env:
            n = env["ir.sequence"].next_by_code("test_sequence_type_2")
            self.assertTrue(n)

    @mute_logger("odoo.db")
    def test_ir_sequence_draw_twice_no_gap(self):
        """Try to draw a number from two transactions.
        This is expected to not work.
        """
        with environment() as env0, environment() as env1:
            # First draw succeeds and holds the row lock.
            n0 = env0["ir.sequence"].next_by_code("test_sequence_type_2")
            self.assertTrue(n0)
            # NOTE: The error has to be an OperationalError
            # s.t. the automatic request retry (service/model.py) works.
            with self.assertRaises(
                psycopg.errors.LockNotAvailable,
                msg="postgresql returned an incorrect errcode",
            ):
                env1["ir.sequence"].next_by_code("test_sequence_type_2")

    @classmethod
    def tearDownClass(cls):
        drop_sequence("test_sequence_type_2")


class TestIrSequenceChangeImplementation(BaseCase):
    """Create sequence objects and change their ``implementation`` field."""

    def test_ir_sequence_1_create(self):
        """Try to create a sequence object."""
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_3",
                    "name": "Test sequence",
                }
            )
            self.assertTrue(seq)
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_4",
                    "name": "Test sequence",
                    "implementation": "no_gap",
                }
            )
            self.assertTrue(seq)

    def test_ir_sequence_2_write(self):
        with environment() as env:
            domain = [("code", "in", ["test_sequence_type_3", "test_sequence_type_4"])]
            seqs = env["ir.sequence"].search(domain)
            seqs.write({"implementation": "standard"})
            seqs.write({"implementation": "no_gap"})

    def test_ir_sequence_3_unlink(self):
        with environment() as env:
            domain = [("code", "in", ["test_sequence_type_3", "test_sequence_type_4"])]
            seqs = env["ir.sequence"].search(domain)
            seqs.unlink()

    @classmethod
    def tearDownClass(cls):
        drop_sequence("test_sequence_type_3")
        drop_sequence("test_sequence_type_4")


class TestIrSequenceGenerate(BaseCase):
    """Create sequence objects and generate some values."""

    def test_ir_sequence_create(self):
        """Try to create a sequence object."""
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_5",
                    "name": "Test sequence",
                }
            )
            self.assertTrue(seq)

        with environment() as env:
            for i in range(1, 10):
                n = env["ir.sequence"].next_by_code("test_sequence_type_5")
                self.assertEqual(n, str(i))

    def test_ir_sequence_create_no_gap(self):
        """Try to create a sequence object."""
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_6",
                    "name": "Test sequence",
                    "implementation": "no_gap",
                }
            )
            self.assertTrue(seq)

        with environment() as env:
            for i in range(1, 10):
                n = env["ir.sequence"].next_by_code("test_sequence_type_6")
                self.assertEqual(n, str(i))

    def test_ir_sequence_prefix(self):
        """test whether the raise a user error for an invalid sequence"""

        # try to create a sequence with invalid prefix
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_7",
                    "name": "Test sequence",
                    "prefix": "%u",
                    "suffix": "",
                }
            )
            self.assertTrue(seq)

            with self.assertRaises(UserError):
                env["ir.sequence"].next_by_code("test_sequence_type_7")

    def test_ir_sequence_interpolation_dict(self):
        """Test date-based interpolation directives in sequence suffix/prefix."""
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_8",
                    "name": "Test sequence",
                    "prefix": "%(year)s/%(month)s/%(day)s/",
                    "suffix": "/%(y)s/%(doy)s/%(woy)s",
                }
            )
            self.assertTrue(seq)
            now = datetime.now()
            self.assertEqual(
                env["ir.sequence"].next_by_code("test_sequence_type_8"),
                now.strftime("%Y/%m/%d/1/%y/%j/%W"),
            )

    def test_ir_sequence_iso_directives(self):
        """Test ISO 8061 date directives in sequence suffix/prefix."""
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_9",
                    "name": "Test sequence",
                    "prefix": "%(isoyear)s/%(isoy)s/",
                    "suffix": "/%(isoweek)s/%(weekday)s",
                }
            )
            self.assertTrue(seq)
            isoyear, isoweek, weekday = datetime.now().isocalendar()
            self.assertEqual(
                env["ir.sequence"].next_by_code("test_sequence_type_9"),
                f"{isoyear}/{isoyear % 100:02d}/1/{isoweek:02d}/{weekday % 7}",
            )

    def test_ir_sequence_suffix(self):
        """test whether a user error is raised for an invalid sequence"""

        # try to create a sequence with invalid suffix
        with environment() as env:
            env["ir.sequence"].create(
                {
                    "code": "test_sequence_type_10",
                    "name": "Test sequence",
                    "prefix": "",
                    "suffix": "/%(invalid)s",
                }
            )
            with self.assertRaisesRegex(UserError, "Invalid prefix or suffix"):
                env["ir.sequence"].next_by_code("test_sequence_type_10")

    @classmethod
    def setUpClass(cls):
        with environment() as env:
            cls._sequence_ids = env["ir.sequence"].search([]).ids

    @classmethod
    def tearDownClass(cls):
        with environment() as env:
            env["ir.sequence"].search([("id", "not in", cls._sequence_ids)]).unlink()


class TestIrSequenceInit(common.TransactionCase):
    def test_00(self):
        """test whether the read method returns the right number_next value
        (from postgreSQL sequence and not ir_sequence value)
        """
        # first creation of sequence (normal)
        seq = self.env["ir.sequence"].create(
            {
                "number_next": 1,
                "company_id": 1,
                "padding": 4,
                "number_increment": 1,
                "implementation": "standard",
                "name": "test-sequence-00",
            }
        )
        # Call next() 4 times, and check the last returned value
        seq.next_by_id()
        seq.next_by_id()
        seq.next_by_id()
        n = seq.next_by_id()
        self.assertEqual(
            n, "0004", "The actual sequence value must be 4. reading : %s" % n
        )
        # reset sequence to 1 by write()
        seq.write({"number_next": 1})
        # Read the value of the current sequence
        n = seq.next_by_id()
        self.assertEqual(
            n, "0001", "The actual sequence value must be 1. reading : %s" % n
        )


class TestIrSequenceSwitchImplementation(common.TransactionCase):
    """Switching ``standard`` -> ``no_gap`` must seed ``number_next`` from the
    live PostgreSQL sequence before dropping it. The standard row's
    ``number_next`` never advances, so numbering would otherwise restart at a
    stale value and issue duplicate document numbers.
    """

    def test_switch_to_no_gap_continues_numbering(self):
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-switch-impl",
                "implementation": "standard",
            }
        )
        for i in range(1, 4):
            self.assertEqual(seq.next_by_id(), str(i))
        seq.write({"implementation": "no_gap"})
        # The row was seeded from the live PG sequence value...
        self.assertEqual(seq.number_next, 4)
        # ...so the numbering continues without duplicates.
        self.assertEqual(seq.next_by_id(), "4")
        self.assertEqual(seq.next_by_id(), "5")

    def test_switch_to_no_gap_explicit_number_next(self):
        """An explicit ``number_next`` in the same write wins over seeding."""
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-switch-impl-explicit",
                "implementation": "standard",
            }
        )
        for i in range(1, 4):
            self.assertEqual(seq.next_by_id(), str(i))
        seq.write({"implementation": "no_gap", "number_next": 100})
        self.assertEqual(seq.next_by_id(), "100")

    def test_switch_to_no_gap_seeds_date_range_subsequences(self):
        """Date-range sub-sequences are seeded from their live PG sequences
        too (via direct UPDATEs, without re-entering write())."""
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-switch-impl-ranges",
                "implementation": "standard",
                "use_date_range": True,
            }
        )
        for i in range(1, 4):
            self.assertEqual(seq.next_by_id(), str(i))
        sub_seq = seq.date_range_ids
        self.assertEqual(len(sub_seq), 1)
        seq.write({"implementation": "no_gap"})
        # Both the main row and the sub-sequence row were seeded from their
        # live PG sequence values before those sequences were dropped...
        self.assertEqual(sub_seq.number_next, 4)
        # ...so the sub-sequence numbering continues without duplicates.
        self.assertEqual(seq.next_by_id(), "4")
        self.assertEqual(seq.next_by_id(), "5")


class TestIrSequenceInterpolationLazy(common.TransactionCase):
    """Pin the lazy ``%(key)s`` interpolation of ``_get_prefix_suffix``: every
    legacy key (plain, ``range_`` and ``current_`` variants) must keep
    formatting exactly as the eager implementation did.
    """

    LEGACY_KEYS = [
        ("year", "%Y"),
        ("month", "%m"),
        ("day", "%d"),
        ("y", "%y"),
        ("doy", "%j"),
        ("woy", "%W"),
        ("weekday", "%w"),
        ("h24", "%H"),
        ("h12", "%I"),
        ("min", "%M"),
        ("sec", "%S"),
        ("isoyear", "%G"),
        ("isoy", "%g"),
        ("isoweek", "%V"),
    ]

    def _create(self, prefix="", suffix=""):
        return self.env["ir.sequence"].create(
            {
                "name": "test-sequence-lazy-interpolation",
                "prefix": prefix,
                "suffix": suffix,
            }
        )

    def test_all_legacy_keys_effective_date(self):
        """Every plain legacy key formats against the effective date."""
        effective = datetime(2024, 3, 7, 14, 5, 9)
        pattern = "/".join(f"%({key})s" for key, _fmt in self.LEGACY_KEYS)
        expected = "/".join(effective.strftime(fmt) for _key, fmt in self.LEGACY_KEYS)
        seq = self._create(prefix=pattern, suffix=pattern)
        prefix, suffix = seq._get_prefix_suffix(date=effective)
        self.assertEqual(prefix, expected)
        self.assertEqual(suffix, expected)

    def test_all_legacy_keys_range_date(self):
        """Every ``range_`` legacy key formats against the range date."""
        range_date = datetime(2023, 11, 30, 3, 45, 58)
        pattern = "/".join(f"%(range_{key})s" for key, _fmt in self.LEGACY_KEYS)
        expected = "/".join(range_date.strftime(fmt) for _key, fmt in self.LEGACY_KEYS)
        seq = self._create(prefix=pattern)
        prefix, suffix = seq._get_prefix_suffix(date_range=range_date)
        self.assertEqual(prefix, expected)
        self.assertEqual(suffix, "")

    def test_current_date_keys(self):
        """``current_`` legacy keys format against the current datetime.

        Only the date-granularity keys are asserted; the time-of-day ones
        (h24, h12, min, sec) would race against the clock and are already
        covered by the effective/range date tests above.
        """
        keys = [
            (key, fmt)
            for key, fmt in self.LEGACY_KEYS
            if key not in ("h24", "h12", "min", "sec")
        ]
        pattern = "/".join(f"%(current_{key})s" for key, _fmt in keys)
        seq = self._create(prefix=pattern)
        now = datetime.now()
        prefix, _suffix = seq._get_prefix_suffix()
        expected = "/".join(now.strftime(fmt) for _key, fmt in keys)
        self.assertEqual(prefix, expected)

    def test_empty_prefix_suffix_short_circuit(self):
        """No prefix and no suffix interpolates to two empty strings."""
        seq = self._create()
        self.assertEqual(seq._get_prefix_suffix(), ("", ""))
        self.assertEqual(seq.next_by_id(), "1")

    def test_placeholder_free_prefix_suffix(self):
        """Placeholder-free patterns pass through unchanged."""
        seq = self._create(prefix="INV/", suffix="/X")
        self.assertEqual(seq._get_prefix_suffix(), ("INV/", "/X"))

    def test_repeated_placeholder(self):
        """A placeholder used twice formats identically both times."""
        effective = datetime(2024, 3, 7, 14, 5, 9)
        seq = self._create(prefix="%(year)s-%(year)s/")
        prefix, _suffix = seq._get_prefix_suffix(date=effective)
        self.assertEqual(prefix, "2024-2024/")

    def test_unknown_prefixed_key_raises_user_error(self):
        """Unknown ``range_``/``current_`` keys still raise a UserError."""
        seq = self._create(prefix="%(range_bogus)s")
        with self.assertRaisesRegex(UserError, "Invalid prefix or suffix"):
            seq._get_prefix_suffix()


class TestIrSequencePredictNextval(common.TransactionCase):
    """Regression coverage for the schema-scoped ``_predict_nextval`` query
    behind ``number_next_actual`` (ISEQ-02).

    The ``increment_by`` subquery now filters ``pg_sequences`` on
    ``schemaname = current_schema``; these tests pin that ``number_next_actual``
    still computes the correct value in the standard single-schema case.
    """

    def test_number_next_actual_reflects_increment(self):
        """``number_next_actual`` predicts the next value honouring the step."""
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-predict",
                "implementation": "standard",
                "number_next": 1,
                "number_increment": 5,
            }
        )
        # Before any draw, the prediction is the starting value.
        self.assertEqual(seq.number_next_actual, 1)
        # After one draw, the prediction advances by the increment.
        seq.next_by_id()
        seq.invalidate_recordset(["number_next_actual"])
        self.assertEqual(seq.number_next_actual, 1 + 5)

    def test_number_next_actual_after_restart(self):
        """After a ``number_next`` reset, the prediction tracks the restart."""
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-predict-restart",
                "implementation": "standard",
                "number_next": 1,
                "number_increment": 1,
            }
        )
        seq.next_by_id()
        seq.write({"number_next": 10})
        seq.invalidate_recordset(["number_next_actual"])
        # The PG sequence was RESTARTed; the next value to be drawn is 10.
        self.assertEqual(seq.number_next_actual, 10)
