from lxml import html as lxml_html

from odoo.tests import TransactionCase, tagged


def _element(fragment):
    return lxml_html.fromstring(fragment)


@tagged("post_install", "-at_install")
class TestFieldFromHtml(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env["html_editor.converter.test"]

    def _convert(self, converter, field_name, fragment):
        return self.env[converter].from_html(
            self.model._name,
            self.model._fields[field_name],
            _element(fragment),
        )

    def test_integer_drops_the_thousands_separator(self):
        self.assertEqual(
            self._convert("ir.qweb.field.integer", "integer", "<span>1,234</span>"),
            1234,
        )

    def test_integer_without_separator(self):
        self.assertEqual(
            self._convert("ir.qweb.field.integer", "integer", "<span>7</span>"),
            7,
        )

    def test_float_handles_group_and_decimal_marks(self):
        self.assertEqual(
            self._convert("ir.qweb.field.float", "float", "<span>1,234.56</span>"),
            1234.56,
        )

    def test_base_converter_strips_surrounding_whitespace(self):
        self.assertEqual(
            self._convert("ir.qweb.field", "char", "<span>  hola  </span>"),
            "hola",
        )

    def test_empty_content_becomes_false(self):
        self.assertFalse(
            self._convert("ir.qweb.field", "char", "<span>   </span>"),
        )

    def test_nested_markup_is_read_as_text(self):
        self.assertEqual(
            self._convert(
                "ir.qweb.field",
                "char",
                "<span>ho<b>l</b>a</span>",
            ),
            "hola",
        )

    def test_date_is_converted_to_the_stored_format(self):
        self.assertEqual(
            self._convert("ir.qweb.field.date", "date", "<span>01/15/2026</span>"),
            "2026-01-15",
        )

    def test_selection_maps_the_label_back_to_its_key(self):
        self.assertEqual(
            self._convert(
                "ir.qweb.field.selection",
                "selection_str",
                "<span>La réponse D</span>",
            ),
            "D",
        )


@tagged("post_install", "-at_install")
class TestFieldAttributes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = cls.env["html_editor.converter.test"].create({"char": "hello"})

    def _attributes(self, record, field_name, **options):
        options.setdefault("translate", False)
        return self.env["ir.qweb.field"].attributes(
            record,
            field_name,
            options,
            values=None,
        )

    def test_placeholder_option_reaches_the_attributes(self):
        attrs = self._attributes(self.record, "char", placeholder="Type here")
        self.assertEqual(attrs["placeholder"], "Type here")

    def test_no_placeholder_without_the_option(self):
        attrs = self._attributes(self.record, "char")
        self.assertNotIn("placeholder", attrs)

    def test_base_language_content_is_marked_translated(self):
        attrs = self._attributes(self.record, "char", translate=True)
        self.assertEqual(attrs["data-oe-translation-state"], "translated")

    def test_translation_state_is_not_emitted_for_other_types(self):
        attrs = self._attributes(self.record, "integer", translate=True)
        self.assertNotIn("data-oe-translation-state", attrs)
