from datetime import date, datetime

from odoo.orm.models.mixins.write import WriteMixin
from odoo.orm.primitives import UPDATE_BATCH_SIZE
from odoo.tests import TransactionCase, tagged


class UniformUpdateCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.plain = self._plain_text_column("test_orm.message")
        self.uniform_calls = []
        self.values_calls = []
        uniform_origin = WriteMixin._update_rows_uniform_sql
        values_origin = WriteMixin._update_rows_values_sql
        case = self

        def uniform_spy(records, fnames, ids, values):
            case.uniform_calls.append((records._name, fnames, len(ids)))
            return uniform_origin(records, fnames, ids, values)

        def values_spy(records, fnames, rows):
            case.values_calls.append((records._name, fnames, len(rows)))
            return values_origin(records, fnames, rows)

        self.patch(WriteMixin, "_update_rows_uniform_sql", uniform_spy)
        self.patch(WriteMixin, "_update_rows_values_sql", values_spy)

    def _plain_text_column(self, model_name):
        """Name a stored text column the collapse is eligible for.

        Naming one in the source is not safe: an installed module may redefine
        it. `test_inherit` does exactly that to `test_orm.message.body`, giving
        it `translate=True`, so a suite that assumes `body` is plain passes on
        its own and fails in any run that installs that module -- which
        `post_install` guarantees. Resolving the column here also keeps the
        negative tests honest: one that asserts a differing row *blocks* the
        collapse proves nothing about a column that could never collapse.
        """
        for field in self.env[model_name]._fields.values():
            if (
                field.store
                and field.type in ("char", "text")
                and not field.translate
                and not field.company_dependent
                and not field.compute
                and not field.related
            ):
                return field.name
        raise AssertionError(
            f"{model_name} has no column the uniform collapse can apply to"
        )

    def _calls_for(self, model_name):
        return (
            [call for call in self.uniform_calls if call[0] == model_name],
            [call for call in self.values_calls if call[0] == model_name],
        )

    def assertCollapsed(self, model_name, message=""):
        self.env.flush_all()
        uniform, values = self._calls_for(model_name)
        self.assertTrue(uniform, f"expected a uniform UPDATE. {message}")
        self.assertFalse(values, f"expected no VALUES join. {message}")

    def assertNotCollapsed(self, model_name, message=""):
        self.env.flush_all()
        uniform, values = self._calls_for(model_name)
        self.assertFalse(uniform, f"expected no uniform UPDATE. {message}")
        self.assertTrue(values, f"expected a VALUES join. {message}")

    def reset_calls(self):
        self.uniform_calls.clear()
        self.values_calls.clear()

    def messages(self, count):
        records = self.env["test_orm.message"].create([{} for _ in range(count)])
        self.env.flush_all()
        self.reset_calls()
        return records

    def companies(self, count):
        records = self.env["test_orm.company"].create([{} for _ in range(count)])
        self.env.flush_all()
        self.reset_calls()
        return records


@tagged("post_install", "-at_install")
class TestUniformUpdateEligibility(UniformUpdateCase):
    def test_plain_scalar_columns_collapse(self):
        records = self.messages(5)
        for fname, value in (
            (self.plain, "shared text"),
            ("important", True),
        ):
            with self.subTest(field=fname):
                self.reset_calls()
                records.write({fname: value})
                self.assertCollapsed("test_orm.message", f"field {fname}")

        mixed = self.env["test_orm.mixed"].create([{} for _ in range(5)])
        self.env.flush_all()
        for fname, value in (("foo", "shared"), ("count", 7), ("truth", True)):
            with self.subTest(field=fname):
                self.reset_calls()
                mixed.write({fname: value})
                self.assertCollapsed("test_orm.mixed", f"field {fname}")

    def test_false_and_none_collapse(self):
        records = self.messages(5)
        records.write({self.plain: "x"})
        self.reset_calls()
        records.write({self.plain: False})
        self.assertCollapsed("test_orm.message")

    def test_temporal_columns_collapse(self):
        records = self.env["test_orm.mixed"].create([{} for _ in range(5)])
        self.env.flush_all()
        self.reset_calls()
        records.write({"date": date(2024, 1, 1)})
        self.assertCollapsed("test_orm.mixed")
        self.reset_calls()
        records.write({"moment": datetime(2024, 1, 1, 12, 0, 0)})
        self.assertCollapsed("test_orm.mixed")

    def test_translated_column_does_not_collapse(self):
        records = self.messages(5)
        records.write({"label": "shared label"})
        self.assertNotCollapsed("test_orm.message", "translate=True")

    def test_company_dependent_columns_do_not_collapse(self):
        records = self.companies(5)
        for fname, value in (
            ("foo", "shared"),
            ("count", 7),
            ("phi", 1.5),
            ("truth", True),
            ("date", "2024-01-01"),
            ("html1", "<p>x</p>"),
        ):
            with self.subTest(field=fname):
                self.reset_calls()
                records.write({fname: value})
                self.assertNotCollapsed("test_orm.company", f"field {fname}")

    def test_one_differing_row_blocks_the_collapse(self):
        records = self.messages(5)
        for index, record in enumerate(records):
            record[self.plain] = "same" if index else "different"
        self.assertNotCollapsed("test_orm.message")

    def test_a_single_record_is_never_collapsed(self):
        record = self.messages(1)
        record.write({self.plain: "solo"})
        self.assertNotCollapsed("test_orm.message")

    def test_mixed_group_is_not_collapsed(self):
        records = self.messages(5)
        records.write({self.plain: "shared", "label": "shared label"})
        self.assertNotCollapsed("test_orm.message")

    def test_two_eligible_columns_collapse_together(self):
        records = self.env["test_orm.mixed"].create([{} for _ in range(5)])
        self.env.flush_all()
        self.reset_calls()
        records.write({"foo": "shared", "count": 4})
        self.assertCollapsed("test_orm.mixed")

    def test_two_columns_one_differing_do_not_collapse(self):
        records = self.env["test_orm.mixed"].create([{} for _ in range(5)])
        self.env.flush_all()
        self.reset_calls()
        for index, record in enumerate(records):
            record.write({"foo": "shared", "count": index})
        self.assertNotCollapsed("test_orm.mixed")

    def test_log_access_columns_do_not_block_the_collapse(self):
        records = self.messages(5)
        self.assertTrue(records._log_access)
        records.write({self.plain: "shared"})
        self.env.flush_all()
        uniform, _values = self._calls_for("test_orm.message")
        self.assertTrue(uniform)
        self.assertIn("write_date", uniform[0][1])
        self.assertIn("write_uid", uniform[0][1])


@tagged("post_install", "-at_install")
class TestUniformUpdateEquivalence(UniformUpdateCase):
    def _write_both_ways(self, count, fname, value, other, seed=None):
        results = []
        for extra in (0, 1):
            records = self.env["test_orm.message"].create(
                [{} for _ in range(count + extra)]
            )
            self.env.flush_all()
            if seed is not None:
                for index, record in enumerate(records):
                    seed(index, record)
                self.env.flush_all()
            self.reset_calls()
            subject = records[:count]
            subject.write({fname: value})
            if extra:
                records[count].write({fname: other})
            self.env.flush_all()
            uniform, values = self._calls_for("test_orm.message")
            self.assertTrue(
                uniform if not extra else values,
                "the write did not take the path this comparison needs",
            )
            self.env.cr.execute(
                f"SELECT {fname} FROM test_orm_message WHERE id = ANY(%s) ORDER BY id",
                [subject.ids],
            )
            results.append([row[0] for row in self.env.cr.fetchall()])
        return results

    def test_equivalent_for_a_plain_column(self):
        collapsed, via_values = self._write_both_ways(
            5, self.plain, "shared text", other="other"
        )
        self.assertEqual(collapsed, via_values)
        self.assertEqual(collapsed, ["shared text"] * 5)

    def test_equivalent_when_overwriting_existing_values(self):
        def seed(index, record):
            record[self.plain] = f"previous {index}"

        collapsed, via_values = self._write_both_ways(
            5, self.plain, "shared", other="other", seed=seed
        )
        self.assertEqual(collapsed, via_values)

    def test_equivalent_from_a_mixed_prior_state(self):

        def seed(index, record):
            if index % 2:
                record[self.plain] = f"previous {index}"

        collapsed, via_values = self._write_both_ways(
            6, self.plain, "shared", other="other", seed=seed
        )
        self.assertEqual(collapsed, via_values)

    def test_equivalent_for_false(self):
        def seed(index, record):
            record[self.plain] = f"previous {index}"

        collapsed, via_values = self._write_both_ways(
            5, self.plain, False, other="kept", seed=seed
        )
        self.assertEqual(collapsed, via_values)
        self.assertEqual(collapsed, [None] * 5)

    def test_equivalent_across_column_types(self):
        for fname, value, other in (
            ("important", True, False),
            (self.plain, "text", "different text"),
        ):
            with self.subTest(field=fname):
                collapsed, via_values = self._write_both_ways(
                    4, fname, value, other=other
                )
                self.assertEqual(collapsed, via_values)

    def test_numeric_values_survive_the_cast(self):
        records = self.env["test_orm.mixed"].create([{} for _ in range(4)])
        self.env.flush_all()
        for value in (1.25, -7.5, 0.0):
            with self.subTest(value=value):
                self.reset_calls()
                records.write({"number": value})
                self.assertCollapsed("test_orm.mixed")
                self.env.invalidate_all()
                self.assertEqual(records.mapped("number"), [value] * 4)


@tagged("post_install", "-at_install")
class TestUniformUpdateStatements(UniformUpdateCase):
    def _update_count(self, records, vals):
        self.reset_calls()
        records.write(vals)
        self.env.flush_all()
        uniform, values = self._calls_for(records._name)
        return len(uniform) + len(values)

    def test_a_uniform_group_is_one_statement_at_any_size(self):
        for count in (2, UPDATE_BATCH_SIZE, UPDATE_BATCH_SIZE + 1):
            with self.subTest(count=count):
                records = self.messages(count)
                self.assertEqual(self._update_count(records, {self.plain: "shared"}), 1)

    def test_a_non_uniform_group_still_batches(self):
        count = UPDATE_BATCH_SIZE + 1
        records = self.messages(count)
        self.reset_calls()
        for index, record in enumerate(records):
            record[self.plain] = f"row {index}"
        self.env.flush_all()
        uniform, values = self._calls_for("test_orm.message")
        self.assertFalse(uniform)
        self.assertEqual(len(values), 2, "ceil(101 / 100)")
        self.assertEqual([call[2] for call in values], [UPDATE_BATCH_SIZE, 1])

    def test_the_collapse_covers_the_whole_group(self):
        count = UPDATE_BATCH_SIZE * 3
        records = self.messages(count)
        self.reset_calls()
        records.write({self.plain: "shared"})
        self.env.flush_all()
        uniform, _values = self._calls_for("test_orm.message")
        self.assertEqual([call[2] for call in uniform], [count])
