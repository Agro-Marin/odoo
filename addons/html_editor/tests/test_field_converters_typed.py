from lxml import html as lxml_html

from odoo.tests import TransactionCase, tagged


def _element(fragment):
    return lxml_html.fromstring(fragment)


@tagged("post_install", "-at_install")
class TestTypedFieldConverters(TransactionCase):
    """Type-specific inbound converters and their branding attributes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model = cls.env["html_editor.converter.test"]
        cls.record = cls.model.create({"html": "<p>hi</p>"})

    def _from_html(self, converter, field_name, fragment):
        return self.env[converter].from_html(
            self.model._name,
            self.model._fields[field_name],
            _element(fragment),
        )

    def test_text_converter_flattens_line_breaks(self):
        """A text field keeps the visual line breaks as newlines."""
        self.assertEqual(
            self._from_html("ir.qweb.field.text", "text", "<div>a<br/>b</div>"),
            "a\nb",
        )

    def test_selection_rejects_an_unknown_label(self):
        """An edited label outside the selection is refused, not guessed."""
        with self.assertRaises(ValueError):
            self._from_html(
                "ir.qweb.field.selection",
                "selection_str",
                "<span>Not a real option</span>",
            )

    def test_html_converter_keeps_markup_of_children(self):
        """An html field keeps its children's markup, one per line."""
        self.assertEqual(
            self._from_html(
                "ir.qweb.field.html", "html", "<div>t<p>x</p><p>y</p></div>"
            ),
            "t\n<p>x</p>\n<p>y</p>",
        )

    def test_monetary_reads_the_amount_span_only(self):
        """The amount is read from its span, ignoring the currency symbol."""
        self.assertEqual(
            self._from_html(
                "ir.qweb.field.monetary",
                "float",
                '<span class="w"><span>1,234.50</span> $</span>',
            ),
            1234.50,
        )

    def test_duration_is_parsed_unlocalized(self):
        """A duration is stored as a plain float, no locale marks applied."""
        self.assertEqual(
            self._from_html("ir.qweb.field.duration", "float", "<span>2.5</span>"),
            2.5,
        )

    def test_duration_keeps_the_original_value_for_branding(self):
        """Branding carries the pre-edit value so the editor can compare."""
        attrs = self.env["ir.qweb.field.duration"].attributes(
            self.record,
            "float",
            {"inherit_branding": True, "translate": False},
        )
        self.assertEqual(attrs["data-oe-original"], self.record.float)

    def test_duration_branding_absent_without_the_option(self):
        """Without branding the original value is not leaked (boundary)."""
        attrs = self.env["ir.qweb.field.duration"].attributes(
            self.record,
            "float",
            {"inherit_branding": False, "translate": False},
        )
        self.assertNotIn("data-oe-original", attrs)

    def test_sanitized_html_field_declares_its_policy(self):
        """A sanitized html field tells the editor which policy applies."""
        attrs = self.env["ir.qweb.field.html"].attributes(
            self.record,
            "html",
            {"inherit_branding": True, "translate": False},
        )
        # the test field sanitizes attributes, so blocks stay allowed
        self.assertEqual(attrs["data-oe-sanitize"], "no_block")

    def test_html_policy_absent_without_branding(self):
        """No branding means no sanitize directive at all (boundary)."""
        attrs = self.env["ir.qweb.field.html"].attributes(
            self.record,
            "html",
            {"inherit_branding": False, "translate": False},
        )
        self.assertNotIn("data-oe-sanitize", attrs)
