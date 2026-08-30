import datetime
import unittest

from odoo.libs.documents.coerce import to_float
from odoo.libs.documents.format import ABSOLUTE, from_float
from odoo.libs.documents.layout import RIGHT, Field, Layout

ABA = Layout(
    (
        Field("record_type", 1, constant="6"),
        Field("account", 10, align=RIGHT, pad="0"),
        Field("name", 12, truncate=True),
        Field(
            "amount",
            10,
            align=RIGHT,
            pad="0",
            render=lambda v: from_float(v, implied_point=True, sign=ABSOLUTE),
            parse=lambda t: to_float(t) / 100,
        ),
        Field(
            "date",
            8,
            render=lambda v: v.strftime("%d%m%Y"),
            parse=lambda t: datetime.datetime.strptime(t, "%d%m%Y").date(),
        ),
    )
)


class TestField(unittest.TestCase):
    def test_left_pads_on_the_right(self):
        self.assertEqual(Field("n", 5).render_value("ab"), "ab   ")

    def test_right_pads_on_the_left(self):
        self.assertEqual(Field("n", 5, align=RIGHT, pad="0").render_value(7), "07.00")

    def test_a_constant_ignores_the_value(self):
        self.assertEqual(Field("t", 2, constant="6").render_value("x"), "6 ")

    def test_overflow_raises_rather_than_silently_truncating(self):
        with self.assertRaises(ValueError) as caught:
            Field("n", 3).render_value("abcdef")
        self.assertIn("3 characters wide", str(caught.exception))

    def test_truncation_is_opt_in_and_keeps_the_significant_end(self):
        self.assertEqual(Field("n", 3, truncate=True).render_value("abcdef"), "abc")
        self.assertEqual(
            Field("n", 3, align=RIGHT, truncate=True).render_value("abcdef"), "def"
        )

    def test_a_width_must_be_positive(self):
        with self.assertRaises(ValueError):
            Field("n", 0)

    def test_an_alignment_must_be_known(self):
        with self.assertRaises(ValueError):
            Field("n", 3, align="centre")

    def test_padding_is_one_character(self):
        with self.assertRaises(ValueError):
            Field("n", 3, pad="ab")

    def test_a_constant_must_fit(self):
        with self.assertRaises(ValueError):
            Field("t", 2, constant="666")

    def test_options_reach_the_format_layer(self):
        item = Field("n", 9, align=RIGHT, options={"thousand": ".", "decimal": ","})
        self.assertEqual(item.render_value(1234.5), " 1.234,50")


class TestLayout(unittest.TestCase):
    def test_width_is_the_sum_of_its_fields(self):
        self.assertEqual(ABA.width, 41)

    def test_names(self):
        self.assertEqual(
            ABA.names, ("record_type", "account", "name", "amount", "date")
        )

    def test_a_record_renders_to_its_width(self):
        line = ABA.render(
            {
                "account": "12345",
                "name": "AgroMarin SA de CV",
                "amount": 1234.56,
                "date": datetime.date(2026, 8, 29),
            }
        )
        self.assertEqual(len(line), ABA.width)
        self.assertEqual(line, "60000012345AgroMarin SA000012345629082026")

    def test_a_missing_value_is_blank_not_a_crash(self):
        line = Layout((Field("a", 3), Field("b", 3))).render({"a": "x"})
        self.assertEqual(line, "x     ")

    def test_render_all_terminates_each_record(self):
        layout = Layout((Field("a", 2),))
        self.assertEqual(layout.render_all([{"a": "x"}, {"a": "y"}]), "x \r\ny \r\n")

    def test_a_layout_needs_a_field(self):
        with self.assertRaises(ValueError):
            Layout(())

    def test_a_layout_names_each_field_once(self):
        with self.assertRaises(ValueError):
            Layout((Field("a", 2), Field("a", 3)))


class TestLayoutParse(unittest.TestCase):
    def test_a_line_reads_back_as_the_record_that_wrote_it(self):
        record = {
            "record_type": "6",
            "account": "12345",
            "name": "AgroMarin S",
            "amount": 1234.56,
            "date": datetime.date(2026, 8, 29),
        }
        line = ABA.render(record)
        read = ABA.parse(line)
        self.assertEqual(read["record_type"], "6")
        self.assertEqual(read["name"], "AgroMarin S")
        self.assertAlmostEqual(read["amount"], 1234.56, places=2)
        self.assertEqual(read["date"], datetime.date(2026, 8, 29))

    def test_padding_is_stripped_from_the_padded_end_only(self):
        layout = Layout((Field("a", 6, align=RIGHT, pad="0"),))
        self.assertEqual(layout.parse("001230")["a"], "1230")

    def test_a_short_line_is_a_defect_not_something_to_pad(self):
        with self.assertRaises(ValueError) as caught:
            ABA.parse("6000001234")
        self.assertIn("layout is 41", str(caught.exception))

    def test_trailing_content_beyond_the_layout_is_ignored(self):
        layout = Layout((Field("a", 2),))
        self.assertEqual(layout.parse("xy and more"), {"a": "xy"})
