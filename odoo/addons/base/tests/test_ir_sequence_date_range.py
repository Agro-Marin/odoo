from datetime import date

from odoo.tests.common import SingleTransactionCase, TransactionCase
from odoo.tools.misc import mute_logger


class TestIrSequenceDateRangeStandard(SingleTransactionCase):
    """A few tests for a 'Standard' (i.e. PostgreSQL) sequence."""

    def test_ir_sequence_date_range_1_create(self):
        """Try to create a sequence object with date ranges enabled."""
        seq = self.env["ir.sequence"].create(
            {
                "code": "test_sequence_date_range",
                "name": "Test sequence",
                "use_date_range": True,
            }
        )
        self.assertTrue(seq)

    def test_ir_sequence_date_range_2_change_dates(self):
        """Draw numbers to create a subsequence, change its date range, then
        draw again and check a new subsequence was created."""
        year = date.today().year - 1

        def january(d):
            return date(year, 1, d)

        seq16 = self.env["ir.sequence"].with_context(ir_sequence_date=january(16))
        n = seq16.next_by_code("test_sequence_date_range")
        self.assertEqual(n, "1")
        n = seq16.next_by_code("test_sequence_date_range")
        self.assertEqual(n, "2")

        # modify the range of date created
        domain = [
            ("sequence_id.code", "=", "test_sequence_date_range"),
            ("date_from", "=", january(1)),
        ]
        seq_date_range = self.env["ir.sequence.date_range"].search(domain)
        seq_date_range.write({"date_from": january(18)})
        n = seq16.next_by_code("test_sequence_date_range")
        self.assertEqual(n, "1")

        # check the newly created sequence stops at the 17th of January
        domain = [
            ("sequence_id.code", "=", "test_sequence_date_range"),
            ("date_from", "=", january(1)),
        ]
        seq_date_range = self.env["ir.sequence.date_range"].search(domain)
        self.assertEqual(seq_date_range.date_to, january(17))

    def test_ir_sequence_date_range_3_unlink(self):
        seq = self.env["ir.sequence"].search(
            [("code", "=", "test_sequence_date_range")]
        )
        seq.unlink()


class TestIrSequenceDateRangeNoGap(SingleTransactionCase):
    """Copy of the previous tests for a 'No gap' sequence."""

    def test_ir_sequence_date_range_1_create_no_gap(self):
        """Try to create a sequence object."""
        seq = self.env["ir.sequence"].create(
            {
                "code": "test_sequence_date_range_2",
                "name": "Test sequence",
                "use_date_range": True,
                "implementation": "no_gap",
            }
        )
        self.assertTrue(seq)

    def test_ir_sequence_date_range_2_change_dates(self):
        """Draw numbers to create a subsequence, change its date range, then
        draw again and check a new subsequence was created."""
        year = date.today().year - 1

        def january(d):
            return date(year, 1, d)

        seq16 = self.env["ir.sequence"].with_context({"ir_sequence_date": january(16)})
        n = seq16.next_by_code("test_sequence_date_range_2")
        self.assertEqual(n, "1")
        n = seq16.next_by_code("test_sequence_date_range_2")
        self.assertEqual(n, "2")

        # modify the range of date created
        domain = [
            ("sequence_id.code", "=", "test_sequence_date_range_2"),
            ("date_from", "=", january(1)),
        ]
        seq_date_range = self.env["ir.sequence.date_range"].search(domain)
        seq_date_range.write({"date_from": january(18)})
        n = seq16.next_by_code("test_sequence_date_range_2")
        self.assertEqual(n, "1")

        # check the newly created sequence stops at the 17th of January
        domain = [
            ("sequence_id.code", "=", "test_sequence_date_range_2"),
            ("date_from", "=", january(1)),
        ]
        seq_date_range = self.env["ir.sequence.date_range"].search(domain)
        self.assertEqual(seq_date_range.date_to, january(17))

    def test_ir_sequence_date_range_3_unlink(self):
        seq = self.env["ir.sequence"].search(
            [("code", "=", "test_sequence_date_range_2")]
        )
        seq.unlink()


class TestIrSequenceDateRangeChangeImplementation(SingleTransactionCase):
    """Create sequence objects and change their ``implementation`` field."""

    def test_ir_sequence_date_range_1_create(self):
        """Try to create a sequence object."""
        seq = self.env["ir.sequence"].create(
            {
                "code": "test_sequence_date_range_3",
                "name": "Test sequence",
                "use_date_range": True,
            }
        )
        self.assertTrue(seq)

        seq = self.env["ir.sequence"].create(
            {
                "code": "test_sequence_date_range_4",
                "name": "Test sequence",
                "use_date_range": True,
                "implementation": "no_gap",
            }
        )
        self.assertTrue(seq)

    def test_ir_sequence_date_range_2_use(self):
        """Make some use of the sequences to create some subsequences"""
        year = date.today().year - 1

        def january(d):
            return date(year, 1, d)

        seq = self.env["ir.sequence"]
        seq16 = self.env["ir.sequence"].with_context({"ir_sequence_date": january(16)})

        for i in range(1, 5):
            n = seq.next_by_code("test_sequence_date_range_3")
            self.assertEqual(n, str(i))
        for i in range(1, 5):
            n = seq16.next_by_code("test_sequence_date_range_3")
            self.assertEqual(n, str(i))
        for i in range(1, 5):
            n = seq.next_by_code("test_sequence_date_range_4")
            self.assertEqual(n, str(i))
        for i in range(1, 5):
            n = seq16.next_by_code("test_sequence_date_range_4")
            self.assertEqual(n, str(i))

    def test_ir_sequence_date_range_3_write(self):
        """swap the implementation method on both"""
        domain = [
            (
                "code",
                "in",
                ["test_sequence_date_range_3", "test_sequence_date_range_4"],
            )
        ]
        seqs = self.env["ir.sequence"].search(domain)
        seqs.write({"implementation": "standard"})
        seqs.write({"implementation": "no_gap"})

    def test_ir_sequence_date_range_4_unlink(self):
        domain = [
            (
                "code",
                "in",
                ["test_sequence_date_range_3", "test_sequence_date_range_4"],
            )
        ]
        seqs = self.env["ir.sequence"].search(domain)
        seqs.unlink()


class TestIrSequenceDateRangeSwitchImplementation(TransactionCase):
    """Switching ``standard`` -> ``no_gap`` must seed each date-range
    sub-sequence's ``number_next`` from its live PostgreSQL sequence value
    before dropping it, so the sub-sequence numbering continues without
    duplicates.
    """

    def test_switch_to_no_gap_continues_subsequence_numbering(self):
        year = date.today().year - 1
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-date-range-switch",
                "use_date_range": True,
                "implementation": "standard",
            }
        )
        for i in range(1, 4):
            self.assertEqual(seq.next_by_id(sequence_date=date(year, 6, 15)), str(i))
        seq.write({"implementation": "no_gap"})
        # The sub-sequence was seeded from its live PG sequence value.
        self.assertEqual(seq.date_range_ids.number_next, 4)
        self.assertEqual(seq.next_by_id(sequence_date=date(year, 6, 15)), "4")


class TestIrSequenceDateRangeClamp(TransactionCase):
    """A new date range must clamp against the *nearest* following range, not
    the furthest-future one — otherwise it overlaps the intermediate ranges.
    """

    def test_new_range_clamps_to_nearest_following_range(self):
        year = date.today().year - 1
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-date-range-clamp",
                "use_date_range": True,
            }
        )
        # two pre-existing ranges later in the same year
        self.env["ir.sequence.date_range"].create(
            [
                {
                    "sequence_id": seq.id,
                    "date_from": date(year, 5, 1),
                    "date_to": date(year, 5, 31),
                },
                {
                    "sequence_id": seq.id,
                    "date_from": date(year, 9, 1),
                    "date_to": date(year, 9, 30),
                },
            ]
        )
        # drawing before both creates a new range covering the draw date
        seq.next_by_id(sequence_date=date(year, 2, 15))
        new_range = self.env["ir.sequence.date_range"].search(
            [
                ("sequence_id", "=", seq.id),
                ("date_from", "<=", date(year, 2, 15)),
                ("date_to", ">=", date(year, 2, 15)),
            ]
        )
        self.assertEqual(len(new_range), 1)
        self.assertEqual(new_range.date_from, date(year, 1, 1))
        # clamped to the nearest following range (May), not against the
        # September one (which would leave it overlapping May)
        self.assertEqual(new_range.date_to, date(year, 4, 30))


class TestIrSequenceDateRangeConcurrentCreate(TransactionCase):
    """A UniqueViolation on the range insert (two transactions both
    search-missed and created the same range) must be recovered by returning
    the existing range instead of surfacing the raw constraint error.
    """

    @mute_logger("odoo.db")
    def test_conflicting_range_creation_recovers(self):
        year = date.today().year - 1
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-date-range-conflict",
                "use_date_range": True,
            }
        )
        dt = date(year, 6, 15)
        first = seq._create_date_range_seq(dt)
        # simulate the concurrent search-miss: a second create attempt
        # computes the same range and hits the unique constraint
        second = seq._create_date_range_seq(dt)
        self.assertEqual(first.id, second.id)
