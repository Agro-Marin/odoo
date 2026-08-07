from datetime import date

from odoo.tests.common import SingleTransactionCase, TransactionCase
from odoo.tools.misc import mute_logger


class TestIrSequenceDateRangeStandard(SingleTransactionCase):
    def test_ir_sequence_date_range_1_create(self):
        seq = self.env["ir.sequence"].create(
            {
                "code": "test_sequence_date_range",
                "name": "Test sequence",
                "use_date_range": True,
            }
        )
        self.assertTrue(seq)

    def test_ir_sequence_date_range_2_change_dates(self):
        year = date.today().year - 1

        def january(d):
            return date(year, 1, d)

        seq16 = self.env["ir.sequence"].with_context(ir_sequence_date=january(16))
        n = seq16.next_by_code("test_sequence_date_range")
        self.assertEqual(n, "1")
        n = seq16.next_by_code("test_sequence_date_range")
        self.assertEqual(n, "2")

        domain = [
            ("sequence_id.code", "=", "test_sequence_date_range"),
            ("date_from", "=", january(1)),
        ]
        seq_date_range = self.env["ir.sequence.date_range"].search(domain)
        seq_date_range.write({"date_from": january(18)})
        n = seq16.next_by_code("test_sequence_date_range")
        self.assertEqual(n, "1")

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
    def test_ir_sequence_date_range_1_create_no_gap(self):
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
        year = date.today().year - 1

        def january(d):
            return date(year, 1, d)

        seq16 = self.env["ir.sequence"].with_context({"ir_sequence_date": january(16)})
        n = seq16.next_by_code("test_sequence_date_range_2")
        self.assertEqual(n, "1")
        n = seq16.next_by_code("test_sequence_date_range_2")
        self.assertEqual(n, "2")

        domain = [
            ("sequence_id.code", "=", "test_sequence_date_range_2"),
            ("date_from", "=", january(1)),
        ]
        seq_date_range = self.env["ir.sequence.date_range"].search(domain)
        seq_date_range.write({"date_from": january(18)})
        n = seq16.next_by_code("test_sequence_date_range_2")
        self.assertEqual(n, "1")

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
    def test_ir_sequence_date_range_1_create(self):
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
        self.assertEqual(seq.date_range_ids.number_next, 4)
        self.assertEqual(seq.next_by_id(sequence_date=date(year, 6, 15)), "4")


class TestIrSequenceDateRangeClamp(TransactionCase):
    def test_new_range_clamps_to_nearest_following_range(self):
        year = date.today().year - 1
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-date-range-clamp",
                "use_date_range": True,
            }
        )
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
        self.assertEqual(new_range.date_to, date(year, 4, 30))


class TestIrSequenceDateRangeConcurrentCreate(TransactionCase):
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
        second = seq._create_date_range_seq(dt)
        self.assertEqual(first.id, second.id)


class TestIrSequenceDateRangeSwitchToStandard(TransactionCase):
    def test_switch_to_standard_continues_subsequence_numbering(self):
        year = date.today().year - 1
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-date-range-switch-standard",
                "use_date_range": True,
                "implementation": "no_gap",
            }
        )
        for i in range(1, 4):
            self.assertEqual(seq.next_by_id(sequence_date=date(year, 6, 15)), str(i))
        for i in range(1, 3):
            self.assertEqual(
                seq.next_by_id(sequence_date=date(year - 1, 6, 15)), str(i)
            )

        seq.write({"implementation": "standard"})

        self.assertEqual(seq.next_by_id(sequence_date=date(year, 6, 15)), "4")
        self.assertEqual(seq.next_by_id(sequence_date=date(year - 1, 6, 15)), "3")


class TestIrSequencePlainSequenceDate(TransactionCase):
    def _make(self, **extra):
        return self.env["ir.sequence"].create(
            {
                "name": "test-sequence-plain-date",
                "prefix": "%(year)s/%(month)s/",
                "padding": 3,
                **extra,
            }
        )

    def test_plain_sequence_honours_sequence_date(self):
        seq = self._make()
        self.assertEqual(seq.next_by_id(sequence_date=date(2001, 2, 3)), "2001/02/001")

    def test_plain_sequence_matches_date_ranged_and_preview(self):
        dt = date(2001, 2, 3)
        plain = self._make()
        ranged = self._make(use_date_range=True)
        self.assertEqual(
            plain.preview_next(sequence_date=dt), plain.next_by_id(sequence_date=dt)
        )
        self.assertEqual(
            plain.next_by_id(sequence_date=dt)[:8],
            ranged.next_by_id(sequence_date=dt)[:8],
        )

    def test_plain_sequence_without_date_uses_now_in_user_tz(self):
        seq = self._make()
        today = date.today()
        self.assertEqual(seq.next_by_id(), f"{today.year:04d}/{today.month:02d}/001")


class TestIrSequenceDateRangeSeeding(TransactionCase):
    def setUp(self):
        super().setUp()
        self.seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-date-range-seeding",
                "use_date_range": True,
                "implementation": "standard",
                "padding": 3,
            }
        )

    def _make_range(self, year, **vals):
        return self.env["ir.sequence.date_range"].create(
            {
                "sequence_id": self.seq.id,
                "date_from": date(year, 1, 1),
                "date_to": date(year, 12, 31),
                **vals,
            }
        )

    def test_explicit_number_next_is_kept(self):
        rng = self._make_range(2033, number_next=50)
        self.assertEqual(rng.number_next, 50)
        self.assertEqual(self.seq.next_by_id(sequence_date=date(2033, 6, 1)), "050")

    def test_explicit_number_next_actual_is_kept(self):
        rng = self._make_range(2034, number_next_actual=77)
        self.assertEqual(rng.number_next, 77)
        self.assertEqual(self.seq.next_by_id(sequence_date=date(2034, 6, 1)), "077")

    def test_default_range_still_starts_at_one(self):
        rng = self._make_range(2035)
        self.assertEqual(rng.number_next, 1)
        self.assertEqual(self.seq.next_by_id(sequence_date=date(2035, 6, 1)), "001")

    def test_unsaved_range_reports_its_counter(self):
        rng = self.env["ir.sequence.date_range"].new({"sequence_id": self.seq.id})
        self.assertEqual(rng.number_next_actual, 1)

    def test_no_gap_parent_range_keeps_explicit_number_next(self):
        self.seq.write({"implementation": "no_gap"})
        rng = self._make_range(2036, number_next=42)
        self.assertEqual(rng.number_next, 42)
        self.assertEqual(self.seq.next_by_id(sequence_date=date(2036, 6, 1)), "042")
