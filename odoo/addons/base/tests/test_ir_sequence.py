import re
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import psycopg.errors

import odoo
from odoo.exceptions import ConcurrencyError, UserError
from odoo.modules.registry import Registry
from odoo.tests import common
from odoo.tests.common import BaseCase
from odoo.tools.misc import mute_logger

from odoo.addons.base.models.ir_sequence import _INTERPOLATION_FORMATS

ADMIN_USER_ID = common.ADMIN_USER_ID


@contextmanager
def environment():
    registry = Registry(common.get_db_name())
    with registry.cursor() as cr:
        yield odoo.api.Environment(cr, ADMIN_USER_ID, {})


def drop_sequence(code):
    with environment() as env:
        seq = env["ir.sequence"].search([("code", "=", code)])
        seq.unlink()


class TestIrSequenceStandard(BaseCase):
    def test_ir_sequence_create(self):
        with environment() as env:
            seq = env["ir.sequence"].create(
                {
                    "code": "test_sequence_type",
                    "name": "Test sequence",
                }
            )
            self.assertTrue(seq)

    def test_ir_sequence_number_next_zero(self):
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
            seq.write({"number_next": 0})
            self.assertTrue(env["ir.sequence"].next_by_code("test_seq_zero"))
            seq.unlink()

    def test_ir_sequence_search(self):
        with environment() as env:
            seqs = env["ir.sequence"].search([])
            self.assertTrue(seqs)

    def test_ir_sequence_draw(self):
        with environment() as env:
            n = env["ir.sequence"].next_by_code("test_sequence_type")
            self.assertTrue(n)

    def test_ir_sequence_draw_twice(self):
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
    def test_ir_sequence_create_no_gap(self):
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
        with environment() as env:
            n = env["ir.sequence"].next_by_code("test_sequence_type_2")
            self.assertTrue(n)

    @mute_logger("odoo.db")
    def test_ir_sequence_draw_twice_no_gap(self):
        with environment() as env0, environment() as env1:
            n0 = env0["ir.sequence"].next_by_code("test_sequence_type_2")
            self.assertTrue(n0)
            with self.assertRaises(
                psycopg.errors.LockNotAvailable,
                msg="postgresql returned an incorrect errcode",
            ):
                env1["ir.sequence"].next_by_code("test_sequence_type_2")

    @classmethod
    def tearDownClass(cls):
        drop_sequence("test_sequence_type_2")


class TestIrSequenceChangeImplementation(BaseCase):
    def test_ir_sequence_1_create(self):
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
    def test_ir_sequence_create(self):
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
        seq.next_by_id()
        seq.next_by_id()
        seq.next_by_id()
        n = seq.next_by_id()
        self.assertEqual(
            n, "0004", "The actual sequence value must be 4. reading : %s" % n
        )
        seq.write({"number_next": 1})
        n = seq.next_by_id()
        self.assertEqual(
            n, "0001", "The actual sequence value must be 1. reading : %s" % n
        )


class TestIrSequenceSwitchImplementation(common.TransactionCase):
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
        self.assertEqual(seq.number_next, 4)
        self.assertEqual(seq.next_by_id(), "4")
        self.assertEqual(seq.next_by_id(), "5")

    def test_switch_to_no_gap_explicit_number_next(self):
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
        self.assertEqual(sub_seq.number_next, 4)
        self.assertEqual(seq.next_by_id(), "4")
        self.assertEqual(seq.next_by_id(), "5")


class TestIrSequenceInterpolationLazy(common.TransactionCase):
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
        effective = datetime(2024, 3, 7, 14, 5, 9)
        pattern = "/".join(f"%({key})s" for key, _fmt in self.LEGACY_KEYS)
        expected = "/".join(effective.strftime(fmt) for _key, fmt in self.LEGACY_KEYS)
        seq = self._create(prefix=pattern, suffix=pattern)
        prefix, suffix = seq._get_prefix_suffix(date=effective)
        self.assertEqual(prefix, expected)
        self.assertEqual(suffix, expected)

    def test_all_legacy_keys_range_date(self):
        range_date = datetime(2023, 11, 30, 3, 45, 58)
        pattern = "/".join(f"%(range_{key})s" for key, _fmt in self.LEGACY_KEYS)
        expected = "/".join(range_date.strftime(fmt) for _key, fmt in self.LEGACY_KEYS)
        seq = self._create(prefix=pattern)
        prefix, suffix = seq._get_prefix_suffix(date_range=range_date)
        self.assertEqual(prefix, expected)
        self.assertEqual(suffix, "")

    def test_current_date_keys(self):
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
        seq = self._create()
        self.assertEqual(seq._get_prefix_suffix(), ("", ""))
        self.assertEqual(seq.next_by_id(), "1")

    def test_placeholder_free_prefix_suffix(self):
        seq = self._create(prefix="INV/", suffix="/X")
        self.assertEqual(seq._get_prefix_suffix(), ("INV/", "/X"))

    def test_repeated_placeholder(self):
        effective = datetime(2024, 3, 7, 14, 5, 9)
        seq = self._create(prefix="%(year)s-%(year)s/")
        prefix, _suffix = seq._get_prefix_suffix(date=effective)
        self.assertEqual(prefix, "2024-2024/")

    def test_unknown_prefixed_key_raises_user_error(self):
        seq = self._create(prefix="%(range_bogus)s")
        with self.assertRaisesRegex(UserError, "Invalid prefix or suffix"):
            seq._get_prefix_suffix()


class TestIrSequencePredictNextval(common.TransactionCase):
    def test_number_next_actual_reflects_increment(self):
        seq = self.env["ir.sequence"].create(
            {
                "name": "test-sequence-predict",
                "implementation": "standard",
                "number_next": 1,
                "number_increment": 5,
            }
        )
        self.assertEqual(seq.number_next_actual, 1)
        seq.next_by_id()
        seq.invalidate_recordset(["number_next_actual"])
        self.assertEqual(seq.number_next_actual, 1 + 5)

    def test_number_next_actual_after_restart(self):
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
        self.assertEqual(seq.number_next_actual, 10)


class TestIrSequenceDateRangeConcurrency(BaseCase):
    SEQ_CODE = "test_sequence_date_range_race"
    DATE = "2031-06-15"

    def setUp(self):
        super().setUp()
        with environment() as env:
            self.seq_id = (
                env["ir.sequence"]
                .create(
                    {
                        "code": self.SEQ_CODE,
                        "name": "Test date-ranged sequence",
                        "implementation": "no_gap",
                        "use_date_range": True,
                        "prefix": "R/%(range_year)s/",
                        "padding": 4,
                    }
                )
                .id
            )
        self.addCleanup(drop_sequence, self.SEQ_CODE)

    @mute_logger("odoo.db")
    def test_concurrent_range_creation_is_retryable(self):
        registry = Registry(common.get_db_name())
        with registry.cursor() as cr_a, registry.cursor() as cr_b:
            env_a = odoo.api.Environment(cr_a, ADMIN_USER_ID, {})
            env_b = odoo.api.Environment(cr_b, ADMIN_USER_ID, {})
            for env in (env_a, env_b):
                env["ir.sequence.date_range"].search_count(
                    [("sequence_id", "=", self.seq_id)]
                )

            value_a = env_a["ir.sequence"].browse(self.seq_id)._next(self.DATE)
            self.assertEqual(value_a, "R/2031/0001")
            cr_a.commit()

            with self.assertRaises(ConcurrencyError):
                env_b["ir.sequence"].browse(self.seq_id)._next(self.DATE)

    @mute_logger("odoo.db")
    def test_replay_after_concurrent_range_creation_succeeds(self):
        registry = Registry(common.get_db_name())
        with registry.cursor() as cr_a, registry.cursor() as cr_b:
            env_a = odoo.api.Environment(cr_a, ADMIN_USER_ID, {})
            env_b = odoo.api.Environment(cr_b, ADMIN_USER_ID, {})
            for env in (env_a, env_b):
                env["ir.sequence.date_range"].search_count(
                    [("sequence_id", "=", self.seq_id)]
                )

            env_a["ir.sequence"].browse(self.seq_id)._next(self.DATE)
            cr_a.commit()

            with self.assertRaises(ConcurrencyError):
                env_b["ir.sequence"].browse(self.seq_id)._next(self.DATE)

            cr_b.rollback()
            env_b = odoo.api.Environment(cr_b, ADMIN_USER_ID, {})
            self.assertEqual(
                env_b["ir.sequence"].browse(self.seq_id)._next(self.DATE),
                "R/2031/0002",
            )


class TestIrSequenceStepInvariant(common.TransactionCase):
    def _create(self, **vals):
        return self.env["ir.sequence"].create(
            {"name": "step invariant", "padding": 3, **vals}
        )

    def test_no_gap_rejects_zero_step_on_create(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with mute_logger("odoo.db"):
                self._create(implementation="no_gap", number_increment=0)
                self.env.flush_all()

    def test_no_gap_rejects_zero_step_on_write(self):
        sequence = self._create(implementation="no_gap", number_increment=1)
        with self.assertRaises(psycopg.errors.CheckViolation):
            with mute_logger("odoo.db"):
                sequence.write({"number_increment": 0})
                self.env.flush_all()

    def test_standard_rejects_zero_step_on_create(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with mute_logger("odoo.db"):
                self._create(implementation="standard", number_increment=0)
                self.env.flush_all()

    def test_negative_step_is_rejected_before_reaching_postgresql(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with mute_logger("odoo.db"):
                self._create(implementation="standard", number_increment=-1)
                self.env.flush_all()

    def test_negative_padding_is_rejected(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with mute_logger("odoo.db"):
                self._create(number_increment=1, padding=-2)
                self.env.flush_all()

    def test_violation_names_the_invariant(self):
        exc = None
        with mute_logger("odoo.db"):
            try:
                with self.env.cr.savepoint():
                    self._create(implementation="no_gap", number_increment=0)
                    self.env.flush_all()
            except psycopg.errors.IntegrityError as error:
                exc = error
        self.assertEqual(
            self.env["ir.sequence"]._sql_error_to_message(exc),
            "The sequence step must be strictly positive.",
        )

    def test_positive_steps_still_draw_correctly(self):
        no_gap = self._create(
            implementation="no_gap", number_increment=2, number_next=5
        )
        self.assertEqual([no_gap._next() for _ in range(3)], ["005", "007", "009"])
        standard = self._create(
            implementation="standard", number_increment=3, number_next=10
        )
        self.assertEqual([standard._next() for _ in range(3)], ["010", "013", "016"])


class TestIrSequencePatternToRegex(common.TransactionCase):

    def test_every_placeholder_round_trips(self):
        sequence = self.env["ir.sequence"]
        for name in _INTERPOLATION_FORMATS:
            with self.subTest(placeholder=name):
                pattern = f"REF/%({name})s/"
                emitted, _suffix = (
                    self.env["ir.sequence"]
                    .create({"name": name, "prefix": pattern, "padding": 0})
                    ._get_prefix_suffix()
                )
                match = re.match(sequence._pattern_to_regex(pattern), emitted)
                self.assertIsNotNone(
                    match, f"%({name})s emitted {emitted!r}, which its regex rejects"
                )
                self.assertEqual(match.group(name), emitted[4:-1])

    def test_full_generated_name_round_trips(self):
        sequence = self.env["ir.sequence"].create(
            {
                "name": "round trip",
                "prefix": "%(year)s%(month)s/",
                "suffix": "/%(day)s",
                "padding": 5,
            }
        )
        name = sequence.get_next_char(42)
        pattern = "%(year)s%(month)s/00042/%(day)s"
        match = re.match(sequence._pattern_to_regex(pattern), name)
        self.assertIsNotNone(match, f"{name!r} not matched by its own pattern")
        self.assertEqual(match.group("year"), datetime.now().strftime("%Y"))

    def test_repeated_placeholder_is_a_backreference(self):
        regex = self.env["ir.sequence"]._pattern_to_regex("%(y)s-%(y)s")
        self.assertIsNotNone(re.match(regex, "26-26"))
        self.assertIsNone(re.match(regex, "26-27"))

    def test_literals_are_escaped(self):
        regex = self.env["ir.sequence"]._pattern_to_regex("A.C|%(y)s")
        self.assertIsNotNone(re.match(regex, "A.C|26"))
        self.assertIsNone(re.match(regex, "AbC|26"))

    def test_anchored_at_both_ends(self):
        regex = self.env["ir.sequence"]._pattern_to_regex("%(year)s")
        self.assertIsNone(re.match(regex, "2026/EXTRA"))
        self.assertIsNone(re.match(regex, "X2026"))

    def test_unknown_placeholder_is_rejected(self):
        with self.assertRaises(ValueError):
            self.env["ir.sequence"]._pattern_to_regex("%(vendor_lot)s")

    def test_a_caller_can_supply_its_own_vocabulary(self):
        sequence = self.env["ir.sequence"]
        extended = dict(sequence._get_pattern_placeholders(), vendor_lot=r"[A-Z0-9]+")
        match = re.match(
            sequence._pattern_to_regex("%(y)s-%(vendor_lot)s", extended),
            "26-AYE4B1501C",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group("vendor_lot"), "AYE4B1501C")

    def test_the_default_vocabulary_is_the_sequences_own(self):
        sequence = self.env["ir.sequence"]
        extended = dict(sequence._get_pattern_placeholders(), vendor_lot=r"[A-Z0-9]+")
        with patch.object(
            type(sequence), "_get_pattern_placeholders", return_value=extended
        ):
            self.assertIsNotNone(
                re.match(sequence._pattern_to_regex("%(vendor_lot)s"), "AYE4B1501C")
            )


class TestIrSequenceNoGapBatchConcurrency(BaseCase):
    """no_gap exists to guarantee a contiguous run under concurrency.

    Batching takes the same `FOR UPDATE NOWAIT` lock once instead of `count`
    times, so a competing draw must still be refused rather than silently
    interleaved -- which would put a gap in the run no_gap promises.
    """

    SEQ_CODE = "test_sequence_no_gap_batch_race"

    def setUp(self):
        super().setUp()
        with environment() as env:
            self.seq_id = env["ir.sequence"].create({
                "code": self.SEQ_CODE,
                "name": "Test no_gap batch",
                "implementation": "no_gap",
                "prefix": "N-",
                "padding": 4,
            }).id
        self.addCleanup(drop_sequence, self.SEQ_CODE)

    @mute_logger("odoo.db")
    def test_a_competing_draw_is_refused_not_interleaved(self):
        registry = Registry(common.get_db_name())
        with registry.cursor() as cr_a, registry.cursor() as cr_b:
            env_a = odoo.api.Environment(cr_a, ADMIN_USER_ID, {})
            env_b = odoo.api.Environment(cr_b, ADMIN_USER_ID, {})

            drawn = env_a["ir.sequence"].browse(self.seq_id)._next_batch(5)
            self.assertEqual(drawn, ["N-000%d" % n for n in range(1, 6)])

            # `_next` on a contended no_gap row raises the same thing; the
            # batch must not soften it into a silent gap.
            with self.assertRaises(Exception) as batched:
                env_b["ir.sequence"].browse(self.seq_id)._next_batch(5)
            cr_b.rollback()
            with self.assertRaises(Exception) as looped:
                env_b["ir.sequence"].browse(self.seq_id)._next()
            self.assertEqual(type(batched.exception), type(looped.exception))

            cr_a.commit()

    @mute_logger("odoo.db")
    def test_the_run_after_a_committed_batch_continues_where_it_stopped(self):
        registry = Registry(common.get_db_name())
        with registry.cursor() as cr_a:
            env_a = odoo.api.Environment(cr_a, ADMIN_USER_ID, {})
            env_a["ir.sequence"].browse(self.seq_id)._next_batch(5)
            cr_a.commit()
        with registry.cursor() as cr_b:
            env_b = odoo.api.Environment(cr_b, ADMIN_USER_ID, {})
            self.assertEqual(
                env_b["ir.sequence"].browse(self.seq_id)._next_batch(2),
                ["N-0006", "N-0007"],
            )
            cr_b.commit()


class TestIrSequenceNextBatch(common.TransactionCase):
    """`_next_batch` must hand back exactly what a loop of `_next` would.

    Only the number of statements differs, so every test here compares the
    two against each other rather than against a literal.
    """

    def _sequence(self, **extra):
        return self.env["ir.sequence"].create({
            "code": "test_next_batch",
            "name": "Test next batch",
            "prefix": "B-",
            "padding": 4,
            **extra,
        })

    def _drawn_one_at_a_time(self, values, count):
        sequence = self._sequence(**values)
        return [sequence._next() for _ in range(count)]

    def _drawn_in_one_batch(self, values, count):
        return self._sequence(**values)._next_batch(count)

    def test_standard_matches_a_loop_of_next(self):
        values = {"implementation": "standard", "number_increment": 1}
        self.assertEqual(
            self._drawn_in_one_batch(values, 5),
            self._drawn_one_at_a_time(values, 5),
        )

    def test_no_gap_matches_a_loop_of_next(self):
        values = {"implementation": "no_gap", "number_increment": 1}
        self.assertEqual(
            self._drawn_in_one_batch(values, 5),
            self._drawn_one_at_a_time(values, 5),
        )

    def test_a_step_other_than_one_is_honoured(self):
        for implementation in ("standard", "no_gap"):
            with self.subTest(implementation=implementation):
                values = {"implementation": implementation, "number_increment": 7}
                self.assertEqual(
                    self._drawn_in_one_batch(values, 4),
                    self._drawn_one_at_a_time(values, 4),
                )

    def test_no_gap_leaves_no_gap(self):
        """The whole point of the implementation: the reserved run is contiguous."""
        sequence = self._sequence(implementation="no_gap", number_increment=1)
        drawn = sequence._next_batch(6)
        numbers = [int(value.removeprefix("B-")) for value in drawn]
        self.assertEqual(numbers, list(range(numbers[0], numbers[0] + 6)))

    def test_the_sequence_is_left_where_a_loop_would_leave_it(self):
        for implementation in ("standard", "no_gap"):
            with self.subTest(implementation=implementation):
                values = {"implementation": implementation, "number_increment": 3}
                looped = self._sequence(**values)
                [looped._next() for _ in range(4)]
                batched = self._sequence(**values)
                batched._next_batch(4)
                self.assertEqual(batched._next(), looped._next())

    def test_a_date_range_sequence_draws_from_the_range(self):
        values = {"implementation": "standard", "use_date_range": True}
        self.assertEqual(
            self._drawn_in_one_batch(values, 4),
            self._drawn_one_at_a_time(values, 4),
        )
        sequence = self._sequence(**values)
        sequence._next_batch(2)
        self.assertTrue(sequence.date_range_ids, "the range was created, not bypassed")

    def test_a_date_range_no_gap_sequence_matches_too(self):
        values = {"implementation": "no_gap", "use_date_range": True}
        self.assertEqual(
            self._drawn_in_one_batch(values, 4),
            self._drawn_one_at_a_time(values, 4),
        )

    def test_zero_and_negative_ask_for_nothing(self):
        sequence = self._sequence()
        before = sequence.number_next_actual
        self.assertEqual(sequence._next_batch(0), [])
        self.assertEqual(sequence._next_batch(-3), [])
        self.assertEqual(sequence.number_next_actual, before,
                         "asking for nothing must not consume a number")

    def test_one_value_is_the_same_as_next(self):
        for implementation in ("standard", "no_gap"):
            with self.subTest(implementation=implementation):
                values = {"implementation": implementation}
                self.assertEqual(
                    self._drawn_in_one_batch(values, 1),
                    self._drawn_one_at_a_time(values, 1),
                )

    def test_next_by_code_batch_finds_the_same_sequence(self):
        """Two identical sequences, so the loop is not continuing the batch."""
        Sequence = self.env["ir.sequence"]
        self._sequence(code="test_by_code_batched", implementation="standard")
        self._sequence(code="test_by_code_looped", implementation="standard")
        self.assertEqual(
            Sequence.next_by_code_batch("test_by_code_batched", 3),
            [Sequence.next_by_code("test_by_code_looped") for _ in range(3)],
        )

    def test_next_by_code_batch_picks_the_company_sequence_first(self):
        """`next_by_code` orders on `company_id, id`; so must its batch."""
        Sequence = self.env["ir.sequence"]
        self._sequence(code="test_by_code_scoped", company_id=False, prefix="SHARED-")
        self._sequence(code="test_by_code_scoped", company_id=self.env.company.id,
                       prefix="OWN-")
        drawn = Sequence.next_by_code_batch("test_by_code_scoped", 2)
        self.assertTrue(all(value.startswith("OWN-") for value in drawn), drawn)
        self.assertTrue(Sequence.next_by_code("test_by_code_scoped").startswith("OWN-"))

    def test_next_by_code_batch_reports_a_missing_code_like_next_by_code(self):
        Sequence = self.env["ir.sequence"]
        self.assertFalse(Sequence.next_by_code("no_such_sequence_code"))
        self.assertFalse(Sequence.next_by_code_batch("no_such_sequence_code", 3))

    def test_the_batch_costs_one_statement(self):
        """The reason the method exists."""
        for implementation in ("standard", "no_gap"):
            with self.subTest(implementation=implementation):
                sequence = self._sequence(implementation=implementation)
                sequence._next()          # settle any lazy setup
                self.env.flush_all()
                before = self.env.cr.sql_log_count
                sequence._next_batch(20)
                self.assertLessEqual(
                    self.env.cr.sql_log_count - before, 3,
                    "twenty values should not cost twenty statements",
                )
