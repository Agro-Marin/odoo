from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import PENDING, SENTINEL


@tagged("-standard", "hotpath_contracts")
class TestFieldGetContracts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mixed = cls.env["test_orm.mixed"]

    def test_scalar_types_cache_hit(self):
        record = self.Mixed.create(
            {
                "foo": "hello",
                "truth": True,
                "count": 42,
                "number": 3.14,
                "date": "2025-01-15",
                "moment": "2025-01-15 10:30:00",
                "lang": "en_US",
            }
        )
        self.env.flush_all()
        record.invalidate_recordset()
        record.fetch(["foo", "truth", "count", "number", "date", "moment", "lang"])

        self.assertEqual(record.foo, "hello")
        self.assertIs(record.truth, True)
        self.assertEqual(record.count, 42)
        self.assertAlmostEqual(record.number, 3.14, places=2)
        self.assertEqual(str(record.date), "2025-01-15")
        self.assertEqual(record.lang, "en_US")

    def test_scalar_cache_hit_equals_cache_miss(self):
        record = self.Mixed.create(
            {
                "foo": "hello",
                "truth": True,
                "count": 42,
                "number": 3.14,
                "date": "2025-01-15",
                "moment": "2025-01-15 10:30:00",
                "lang": "en_US",
            }
        )
        self.env.flush_all()
        for fname in ("foo", "truth", "count", "number", "date", "moment", "lang"):
            record.invalidate_recordset([fname])
            miss_value = record[fname]
            hit_value = record[fname]
            self.assertEqual(
                hit_value,
                miss_value,
                f"{fname}: cache-hit {hit_value!r} != cache-miss {miss_value!r} "
                "(_make_scalar_get closure diverged from convert_to_record)",
            )

    def test_scalar_none_to_falsy(self):
        record = self.Mixed.create({})
        self.env.flush_all()
        record.invalidate_recordset()
        record.fetch(["foo", "truth", "count", "number", "date", "moment"])

        self.assertIs(record.foo, False)
        self.assertIs(record.truth, False)
        self.assertEqual(record.count, 0)
        self.assertEqual(record.number, 3.14)
        self.assertIs(record.date, False)
        self.assertIs(record.moment, False)

    def test_empty_recordset_returns_falsy(self):
        empty = self.Mixed.browse()
        self.assertIs(empty.foo, False)
        self.assertIs(empty.truth, False)
        self.assertEqual(empty.count, 0)
        self.assertIs(empty.date, False)

    def test_multi_record_raises(self):
        r1 = self.Mixed.create({"foo": "a"})
        r2 = self.Mixed.create({"foo": "b"})
        multi = r1 | r2
        with self.assertRaises(ValueError):
            _ = multi.foo

    def test_many2one_returns_recordset(self):
        record = self.Mixed.create({})
        partner = record.currency_id
        if partner:
            self.assertTrue(hasattr(partner, "_ids"))
            self.assertTrue(hasattr(partner, "env"))


@tagged("-standard", "hotpath_contracts")
class TestFieldGetPending(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Move = cls.env["test_orm.move"]

    def test_stored_computed_after_create(self):
        move = self.Move.create({})
        self.env["test_orm.move_line"].create(
            {
                "move_id": move.id,
                "quantity": 10,
            }
        )
        self.assertEqual(move.quantity, 10)
        self.assertIsNot(move.quantity, PENDING)

    def test_pending_evicted_on_read(self):
        move = self.Move.create({})
        self.env.flush_all()

        field = self.Move._fields["quantity"]
        field_cache = field._get_cache(self.env)
        field_cache[move.id] = PENDING

        value = move.quantity
        self.assertIsNot(value, PENDING)
        self.assertIsInstance(value, int)

    def test_plain_m2o_never_caches_pending(self):
        Line = self.env["test_orm.move_line"]
        field = Line._fields["move_id"]
        self.assertFalse(field.is_stored_computed)

        move = self.Move.create({})
        lines = Line.create([{"move_id": move.id, "quantity": q} for q in (1, 2, 3)])
        self.env.flush_all()
        lines.invalidate_recordset(["move_id"])

        field_cache = field._get_cache(self.env)
        self.assertEqual(lines.mapped("move_id"), move)
        for line in lines:
            self.assertIn(line.id, field_cache)
            self.assertIsNot(field_cache[line.id], PENDING)

        lines.invalidate_recordset(["move_id"])
        for line in lines:
            self.assertNotIn(line.id, field_cache)
        self.assertEqual(lines.mapped("move_id"), move)


@tagged("-standard", "hotpath_contracts")
class TestReadFormatContracts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mixed = cls.env["test_orm.mixed"]

    def _reference_read_format(self, records, fnames):
        result = []
        for record in records:
            vals = {"id": record.id}
            for fname in fnames:
                field = records._fields[fname]
                vals[fname] = field.convert_to_read(record[fname], record, False)
            result.append(vals)
        return result

    def test_scalar_phase1_matches_reference(self):
        records = self.Mixed.browse()
        for i in range(5):
            records |= self.Mixed.create(
                {
                    "foo": f"name_{i}",
                    "truth": i % 2 == 0,
                    "count": i * 10,
                    "number": i * 1.5,
                    "date": f"2025-01-{15 + i:02d}",
                    "moment": f"2025-01-{15 + i:02d} 10:30:00",
                }
            )

        self.env.flush_all()
        records.invalidate_recordset()
        records.fetch(["foo", "truth", "count", "number", "date", "moment"])

        scalar_fnames = ["foo", "truth", "count", "number", "date", "moment"]

        fast_result = records._read_format(fnames=scalar_fnames, load=None)
        ref_result = self._reference_read_format(records, scalar_fnames)

        self.assertEqual(len(fast_result), len(ref_result))
        for fast, ref in zip(fast_result, ref_result, strict=False):
            self.assertEqual(fast["id"], ref["id"])
            for fname in scalar_fnames:
                self.assertEqual(
                    fast[fname],
                    ref[fname],
                    f"Mismatch on {fname}: fast={fast[fname]!r} vs ref={ref[fname]!r} "
                    f"(record id={fast['id']})",
                )

    def test_none_values_phase1(self):
        record = self.Mixed.create({})
        self.env.flush_all()
        record.invalidate_recordset()
        record.fetch(["foo", "truth", "count"])

        result = record._read_format(fnames=["foo", "truth", "count"], load=None)
        self.assertEqual(len(result), 1)
        vals = result[0]
        self.assertIs(vals["foo"], False)
        self.assertIs(vals["truth"], False)
        self.assertEqual(vals["count"], 0)

    def test_many2one_with_and_without_display_name(self):
        record = self.Mixed.create({})
        self.env.flush_all()
        record.invalidate_recordset()
        record.fetch(["currency_id"])

        result_no_load = record._read_format(fnames=["currency_id"], load=None)
        val = result_no_load[0]["currency_id"]
        self.assertTrue(val is False or isinstance(val, int))

        result_classic = record._read_format(
            fnames=["currency_id"], load="_classic_read"
        )
        val = result_classic[0]["currency_id"]
        if val:
            self.assertIsInstance(val, (list, tuple))
            self.assertEqual(len(val), 2)


@tagged("-standard", "hotpath_contracts")
class TestTraversalContracts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Msg = cls.env["test_orm.message"]
        cls.Disc = cls.env["test_orm.discussion"]

    def setUp(self):
        super().setUp()
        self.disc = self.Disc.create(
            {
                "name": "Test Discussion",
                "participants": [Command.link(self.env.uid)],
            }
        )
        self.messages = self.Msg.browse()
        for i in range(10):
            self.messages |= self.Msg.create(
                {
                    "discussion": self.disc.id,
                    "body": f"body_{i}",
                    "important": i % 3 == 0,
                    "priority": i,
                }
            )
        self.env.flush_all()

    def test_mapped_scalar_fast_path(self):
        fast = self.messages.mapped("priority")
        standard = [rec.priority for rec in self.messages]
        self.assertEqual(fast, standard)

    def test_mapped_scalar_with_none(self):
        msg = self.Msg.create({"discussion": self.disc.id, "body": False})
        records = self.messages | msg
        fast = records.mapped("body")
        standard = [rec.body for rec in records]
        self.assertEqual(fast, standard)

    def test_mapped_relational(self):
        result = self.messages.mapped("discussion")
        self.assertTrue(hasattr(result, "_ids"))
        self.assertIn(self.disc.id, result.ids)

    def test_filtered_scalar_fast_path(self):
        fast = self.messages.filtered("important")
        standard = self.messages.filtered(lambda r: r.important)
        self.assertEqual(fast._ids, standard._ids)

    def test_filtered_falsy_field(self):
        with_body = self.messages.filtered("body")
        self.assertEqual(len(with_body), len(self.messages))

        no_body = self.Msg.create({"discussion": self.disc.id, "body": False})
        all_msgs = self.messages | no_body
        filtered = all_msgs.filtered("body")
        self.assertNotIn(no_body.id, filtered.ids)

    def test_sorted_single_field(self):
        fast = self.messages.sorted("priority")
        standard = self.messages.sorted(key=lambda r: r.priority)
        self.assertEqual(fast._ids, standard._ids)

    def test_sorted_descending(self):
        asc = self.messages.sorted("priority")
        desc = self.messages.sorted("priority DESC")
        self.assertEqual(asc._ids, tuple(reversed(desc._ids)))

    def test_sorted_with_nulls(self):
        msg = self.Msg.create({"discussion": self.disc.id})
        records = self.messages | msg
        result = records.sorted("body")
        self.assertEqual(len(result), len(records))

    def test_sorted_multi_field(self):
        result = self.messages.sorted("important DESC, priority")
        important_ids = [r.id for r in result if r.important]
        [r.id for r in result if not r.important]
        all_ids = list(result._ids)
        self.assertEqual(all_ids[: len(important_ids)], important_ids)

    def test_grouped_scalar(self):
        fast = self.messages.grouped("important")
        standard = {}
        for record in self.messages:
            key = record.important
            standard.setdefault(key, self.Msg.browse())
            standard[key] |= record

        self.assertEqual(set(fast.keys()), set(standard.keys()))
        for key in fast:
            self.assertEqual(
                fast[key]._ids,
                standard[key]._ids,
                f"Mismatch for grouped key={key!r}",
            )


@tagged("-standard", "hotpath_contracts")
class TestWriteFlushContracts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Move = cls.env["test_orm.move"]
        cls.Line = cls.env["test_orm.move_line"]

    def test_write_defers_sql(self):
        move = self.Move.create({})
        self.env.flush_all()

        move.tag_repeat = 5
        self.assertEqual(move.tag_repeat, 5)

        field = self.Move._fields["tag_repeat"]
        core = self.env._core
        self.assertTrue(core.has_dirty_field(field))

    def test_flush_writes_to_db(self):
        move = self.Move.create({})
        self.env.flush_all()
        move.tag_repeat = 7
        self.env.flush_all()

        self.env.cr.execute(
            "SELECT tag_repeat FROM test_orm_move WHERE id = %s",
            (move.id,),
        )
        db_value = self.env.cr.fetchone()[0]
        self.assertEqual(db_value, 7)

    def test_recompute_triggers_on_write(self):
        move = self.Move.create({})
        line = self.Line.create({"move_id": move.id, "quantity": 5})
        self.env.flush_all()
        self.assertEqual(move.quantity, 5)

        line.quantity = 15
        self.assertEqual(move.quantity, 15)

    def test_flush_convergence(self):
        tag = self.env["test_orm.multi.tag"].create({"name": "X"})
        move = self.Move.create({"tag_id": tag.id, "tag_repeat": 3})
        self.env.flush_all()

        self.assertEqual(move.tag_string, "XXX")

        move.tag_repeat = 2
        self.env.flush_all()
        self.assertEqual(move.tag_string, "XX")

    def test_multiple_writes_batched(self):
        move = self.Move.create({})
        self.env.flush_all()

        move.tag_repeat = 1
        move.tag_repeat = 2
        move.tag_repeat = 3

        self.env.flush_all()
        self.env.cr.execute(
            "SELECT tag_repeat FROM test_orm_move WHERE id = %s",
            (move.id,),
        )
        self.assertEqual(self.env.cr.fetchone()[0], 3)


@tagged("-standard", "hotpath_contracts")
class TestCreateCacheContracts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Move = cls.env["test_orm.move"]
        cls.Line = cls.env["test_orm.move_line"]

    def test_cache_populated_after_create(self):
        move = self.Move.create({"tag_repeat": 5})
        field = self.Move._fields["tag_repeat"]
        field_cache = field._get_cache(self.env)
        self.assertIn(move.id, field_cache)
        self.assertEqual(field_cache[move.id], 5)

    def test_computed_field_available_after_create(self):
        move = self.Move.create({})
        self.Line.create({"move_id": move.id, "quantity": 7})
        val = move.quantity
        self.assertEqual(val, 7)
        self.assertIsNot(val, PENDING)

    def test_batch_create_cache(self):
        moves = self.Move.create([{"tag_repeat": i} for i in range(5)])
        field = self.Move._fields["tag_repeat"]
        field_cache = field._get_cache(self.env)
        for move in moves:
            self.assertIn(move.id, field_cache)

    def test_create_with_relational(self):
        tag = self.env["test_orm.multi.tag"].create({"name": "T"})
        move = self.Move.create({"tag_id": tag.id})

        field = self.Move._fields["tag_id"]
        field_cache = field._get_cache(self.env)
        self.assertIn(move.id, field_cache)
        self.assertEqual(field_cache[move.id], tag.id)


@tagged("-standard", "hotpath_contracts")
class TestPreconditionAPI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Move = cls.env["test_orm.move"]
        cls.Line = cls.env["test_orm.move_line"]
        cls.Mixed = cls.env["test_orm.mixed"]

    def test_ensure_computed_triggers_recompute(self):
        move = self.Move.create({})
        self.Line.create({"move_id": move.id, "quantity": 12})

        field = self.Move._fields["quantity"]
        field.ensure_computed(move)
        field_cache = field._get_cache(self.env)
        self.assertIn(move.id, field_cache)
        self.assertEqual(field_cache[move.id], 12)
        self.assertIsNot(field_cache[move.id], PENDING)

    def test_ensure_computed_noop_for_non_computed(self):
        move = self.Move.create({"tag_repeat": 5})
        field = self.Move._fields["tag_repeat"]
        field.ensure_computed(move)
        self.assertEqual(move.tag_repeat, 5)

    def test_read_cache_hit(self):
        record = self.Mixed.create({"foo": "test"})
        self.env.flush_all()
        record.invalidate_recordset()
        record.fetch(["foo"])

        field = self.Mixed._fields["foo"]
        hit, value = field.read_cache(record.id, self.env)
        self.assertTrue(hit)
        self.assertEqual(value, "test")

    def test_read_cache_miss(self):
        record = self.Mixed.create({"foo": "test"})
        self.env.flush_all()
        record.invalidate_recordset()

        field = self.Mixed._fields["foo"]
        hit, value = field.read_cache(record.id, self.env)
        self.assertFalse(hit)
        self.assertIs(value, SENTINEL)

    def test_read_cache_pending_is_miss(self):
        move = self.Move.create({})
        self.env.flush_all()

        field = self.Move._fields["quantity"]
        field_cache = field._get_cache(self.env)
        field_cache[move.id] = PENDING

        hit, value = field.read_cache(move.id, self.env)
        self.assertFalse(hit)
        self.assertIs(value, SENTINEL)


@tagged("-standard", "hotpath_contracts")
class TestCacheInvariant(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mixed = cls.env["test_orm.mixed"]

    def test_field_cache_memo_consistency(self):
        self.Mixed.create({"foo": "test"})
        field = self.Mixed._fields["foo"]

        cache_via_method = field._get_cache(self.env)
        memo = self.env.__dict__.get("_field_cache_memo", {})
        if field in memo:
            self.assertIs(cache_via_method, memo[field])

    def test_invalidate_clears_cache(self):
        record = self.Mixed.create({"foo": "test"})
        self.env.flush_all()
        field = self.Mixed._fields["foo"]
        field_cache = field._get_cache(self.env)
        self.assertIn(record.id, field_cache)

        record.invalidate_recordset(["foo"])
        self.assertNotIn(record.id, field_cache)

    def test_flush_clears_dirty(self):
        record = self.Mixed.create({"foo": "initial"})
        self.env.flush_all()

        record.foo = "modified"
        core = self.env._core
        field = self.Mixed._fields["foo"]
        self.assertTrue(core.has_dirty_field(field))

        self.env.flush_all()
        self.assertFalse(core.has_dirty_field(field))


@tagged("-standard", "hotpath_contracts")
class TestModifiedTriggers(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Move = cls.env["test_orm.move"]
        cls.Line = cls.env["test_orm.move_line"]

    def test_o2m_dependency_triggers_parent(self):
        move = self.Move.create({})
        line = self.Line.create({"move_id": move.id, "quantity": 3})
        self.env.flush_all()
        self.assertEqual(move.quantity, 3)

        line.quantity = 10
        self.assertEqual(move.quantity, 10)

    def test_adding_child_triggers_parent(self):
        move = self.Move.create({})
        self.Line.create({"move_id": move.id, "quantity": 5})
        self.env.flush_all()
        self.assertEqual(move.quantity, 5)

        self.Line.create({"move_id": move.id, "quantity": 8})
        self.assertEqual(move.quantity, 13)

    def test_removing_child_triggers_parent(self):
        move = self.Move.create({})
        self.Line.create({"move_id": move.id, "quantity": 5})
        line2 = self.Line.create({"move_id": move.id, "quantity": 8})
        self.env.flush_all()
        self.assertEqual(move.quantity, 13)

        line2.unlink()
        self.assertEqual(move.quantity, 5)

    def test_related_field_propagation(self):
        tag = self.env["test_orm.multi.tag"].create({"name": "A"})
        move = self.Move.create({"tag_id": tag.id, "tag_repeat": 2})
        self.env.flush_all()
        self.assertEqual(move.tag_string, "AA")

        tag.name = "B"
        self.env.flush_all()
        self.assertEqual(move.tag_string, "BB")


@tagged("-standard", "hotpath_contracts")
class TestReadFormatManyRecords(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mixed = cls.env["test_orm.mixed"]

    def test_batch_scalar_identity(self):
        records = self.Mixed.create(
            [{"foo": f"name_{i}", "count": i * 10} for i in range(20)]
        )
        self.env.flush_all()
        records.invalidate_recordset()
        records.fetch(["foo", "count"])

        result = records._read_format(fnames=["foo", "count"], load=None)
        self.assertEqual(len(result), 20)

        by_id = {r["id"]: r for r in result}
        for i, record in enumerate(records):
            vals = by_id[record.id]
            self.assertEqual(vals["foo"], f"name_{i}")
            self.assertEqual(vals["count"], i * 10)

    def test_mixed_cache_hit_and_miss(self):
        records = self.Mixed.create([{"foo": f"name_{i}"} for i in range(5)])
        self.env.flush_all()

        records[2].invalidate_recordset(["foo"])
        records[4].invalidate_recordset(["foo"])

        result = records._read_format(fnames=["foo"], load=None)
        self.assertEqual(len(result), 5)
        for i, vals in enumerate(result):
            self.assertEqual(vals["foo"], f"name_{i}")
