from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.tests import common

from odoo.addons.base.tests.common import DISABLED_MAIL_CONTEXT


class TestQwebFieldTime(common.TransactionCase):
    def value_to_html(self, value, options=None):
        options = options or {}
        return self.env["ir.qweb.field.time"].value_to_html(value, options)

    def test_time_value_to_html(self):
        default_fmt = {"format": "h:mm a"}
        self.assertEqual(self.value_to_html(0, default_fmt), "12:00 AM")

        self.assertEqual(self.value_to_html(11.75, default_fmt), "11:45 AM")

        self.assertEqual(self.value_to_html(12, default_fmt), "12:00 PM")

        self.assertEqual(self.value_to_html(14.25, default_fmt), "2:15 PM")

        self.assertEqual(self.value_to_html(15.1, {"format": "HH:mm:SS"}), "15:06:00")

        # Only positive values can be used
        with self.assertRaises(ValueError):
            self.value_to_html(-6.5)

        # Only values less than 24 can be used
        with self.assertRaises(ValueError):
            self.value_to_html(24)


class TestQwebFieldInteger(common.TransactionCase):
    def value_to_html(self, value, options=None):
        options = options or {}
        return self.env["ir.qweb.field.integer"].value_to_html(value, options)

    def test_integer_value_to_html(self):
        self.assertEqual(self.value_to_html(1000), "1,000")
        self.assertEqual(
            self.value_to_html(1000000, {"format_decimalized_number": True}),
            "1M",
        )
        self.assertEqual(
            self.value_to_html(
                125125,
                {"format_decimalized_number": True, "precision_digits": 3},
            ),
            "125.125k",
        )


class TestQwebFieldFloatConverter(common.TransactionCase):
    def value_to_html(self, value, options=None):
        options = options or {}
        return self.env["ir.qweb.field.float"].value_to_html(value, options)

    def test_float_value_to_html_no_precision(self):
        self.assertEqual(self.value_to_html(3), "3.0")
        self.assertEqual(self.value_to_html(3.1), "3.1")
        self.assertEqual(self.value_to_html(3.1231239), "3.123124")

    def test_float_value_to_html_with_precision(self):
        options = {"precision": 3}
        self.assertEqual(self.value_to_html(3, options), "3.000")
        self.assertEqual(self.value_to_html(3.1, options), "3.100")
        self.assertEqual(self.value_to_html(3.123, options), "3.123")
        self.assertEqual(self.value_to_html(3.1239, options), "3.124")

    def test_float_value_to_html_with_min_precision(self):
        options = {"min_precision": 3}
        self.assertEqual(self.value_to_html(0, options), "0.000")
        self.assertEqual(self.value_to_html(3, options), "3.000")
        self.assertEqual(self.value_to_html(3.1, options), "3.100")
        self.assertEqual(self.value_to_html(3.123, options), "3.123")
        self.assertEqual(self.value_to_html(3.1239, options), "3.1239")
        self.assertEqual(self.value_to_html(3.1231239, options), "3.123124")
        self.assertEqual(
            self.value_to_html(1234567890.1234567890, options),
            "1,234,567,890.12346",
        )

    def test_float_value_to_html_with_precision_and_min_precision(self):
        options = {"min_precision": 3, "precision": 4}
        self.assertEqual(self.value_to_html(3, options), "3.000")
        self.assertEqual(self.value_to_html(3.1, options), "3.100")
        self.assertEqual(self.value_to_html(3.123, options), "3.123")
        self.assertEqual(self.value_to_html(3.1239, options), "3.1239")
        self.assertEqual(self.value_to_html(3.12349, options), "3.1235")


class TestQwebFieldFloatTime(common.TransactionCase):
    """QF-T3: ``float_time`` widget (hours-as-fraction -> HH:MM)."""

    def value_to_html(self, value, options=None):
        return self.env["ir.qweb.field.float_time"].value_to_html(value, options or {})

    def test_float_time_value_to_html(self):
        self.assertEqual(self.value_to_html(1.5), "01:30")
        self.assertEqual(self.value_to_html(0), "00:00")
        self.assertEqual(self.value_to_html(2.25), "02:15")
        self.assertEqual(self.value_to_html(-1.5), "-01:30")


class TestQwebFieldDuration(common.TransactionCase):
    """QF-T4: ``duration`` widget, incl. the digital branch and ``round`` > hour clamp."""

    def value_to_html(self, value, options=None):
        return self.env["ir.qweb.field.duration"].value_to_html(value, options or {})

    def test_duration_digital_positive(self):
        self.assertEqual(
            self.value_to_html(1.5, {"unit": "hour", "digital": True}), "01:30:00"
        )

    def test_duration_digital_round_clamped_to_hour(self):
        # round='day' (86400s) exceeds an hour; digital output clamps it to 3600.
        self.assertEqual(
            self.value_to_html(1.5, {"unit": "hour", "round": "day", "digital": True}),
            "02",
        )

    def test_duration_textual_formats(self):
        self.assertEqual(self.value_to_html(1.5, {"unit": "hour"}), "1 hour 30 minutes")
        self.assertEqual(
            self.value_to_html(90, {"unit": "minute", "format": "short"}),
            "1 hr 30 min",
        )


class TestQwebFieldRelative(common.TransactionCase):
    """QF-T5: ``relative`` widget. Regression for the t-out path, which reached
    ``value_to_html`` with no ``now`` option and raised ``KeyError`` instead of
    defaulting to the current time."""

    def value_to_html(self, value, options=None):
        return self.env["ir.qweb.field.relative"].value_to_html(value, options or {})

    def test_relative_without_now_defaults_to_current_time(self):
        # The bare-value (t-out widget) path supplies no ``now``; must not crash.
        result = self.value_to_html(fields.Datetime.from_string("2000-01-01 00:00:00"))
        self.assertIn("ago", result)

    def test_relative_with_explicit_now(self):
        result = self.value_to_html(
            fields.Datetime.from_string("2020-01-01 00:00:00"),
            {"now": "2020-01-02 00:00:00"},
        )
        self.assertEqual(result, "1 day ago")

    def test_relative_on_date_value(self):
        # A bare ``date`` (date field value) must be comparable with the
        # datetime reference instead of raising TypeError.
        result = self.value_to_html(date(2000, 1, 1))
        self.assertIn("ago", result)

    def test_relative_record_to_html_date_field(self):
        # Regression: ``record_to_html`` called ``field.now()`` which does not
        # exist on ``fields.Date`` (AttributeError on any date field).
        rate = self.env["res.currency.rate"].create(
            {
                "currency_id": self.env.ref("base.EUR").id,
                "name": "2020-01-01",
                "rate": 1.5,
            }
        )
        result = self.env["ir.qweb.field.relative"].record_to_html(rate, "name", {})
        self.assertIn("ago", result)


class TestQwebFieldRecordContext(common.TransactionCase):
    """``record_to_html`` propagates only the curated presentation context
    (template cache keys + tz/bin_size) onto the record, not the qweb
    per-render internals."""

    QWEB_INTERNALS = (
        "__qweb_loaded_functions",
        "__qweb_compiled_cache",
        "__qweb_loaded_codes",
        "__qweb_loaded_options",
        "_qweb_error_path_xml",
    )

    def test_record_to_html_curates_record_context(self):
        partner = self.env["res.partner"].create({"name": "Ctx Probe"})
        Partner = self.registry["res.partner"]
        seen_contexts = []
        orig_compute = Partner._compute_display_name

        def spy(records):
            seen_contexts.append(records.env.context)
            return orig_compute(records)

        converter = self.env["ir.qweb.field"].with_context(
            tz="Pacific/Auckland",
            __qweb_loaded_functions={},
            __qweb_compiled_cache={},
            __qweb_loaded_codes={},
            __qweb_loaded_options={},
            _qweb_error_path_xml=[None, None, None],
        )
        with patch.object(Partner, "_compute_display_name", spy):
            partner.invalidate_recordset(["display_name"])
            result = converter.record_to_html(partner, "display_name", {})
        self.assertEqual(result, "Ctx Probe")
        self.assertTrue(seen_contexts, "the field compute did not run")
        # curated presentation keys are propagated onto the record...
        self.assertEqual(seen_contexts[-1].get("tz"), "Pacific/Auckland")
        # ...the render-internal state is not
        for context in seen_contexts:
            for key in self.QWEB_INTERNALS:
                self.assertNotIn(key, context)

    def test_record_to_html_skips_rebind_on_matching_context(self):
        partner = self.env["res.partner"].create({"name": "Same Ctx"})
        converter = self.env["ir.qweb.field"]
        with patch.object(
            type(partner), "with_context", side_effect=AssertionError
        ) as rebind:
            result = converter.record_to_html(partner, "name", {})
        self.assertEqual(result, "Same Ctx")
        rebind.assert_not_called()


class TestQwebFieldSelectionRecord(common.TransactionCase):
    def test_selection_record_to_html_label(self):
        # The selection label is resolved from the field's selection pairs
        # (via ``_description_selection``), not the raw stored value.
        partner = self.env["res.partner"].create({"name": "Sel Probe"})
        result = self.env["ir.qweb.field.selection"].record_to_html(
            partner, "company_type", {}
        )
        # equivalence with the full-description path it replaced
        field = partner._fields["company_type"]
        expected = dict(field.get_description(self.env)["selection"])["person"]
        self.assertEqual(result, expected)
        self.assertNotEqual(result, "person", "label, not raw value, expected")


class TestQwebFieldMonetaryType(common.TransactionCase):
    """QF-T6: monetary must reject non-numbers, including bool (an int subclass)."""

    def test_monetary_rejects_bool(self):
        currency = self.env["res.currency"].search([], limit=1)
        with self.assertRaises(TypeError):
            self.env["ir.qweb.field.monetary"].value_to_html(
                True, {"display_currency": currency}
            )


class TestQwebFieldContact(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, **DISABLED_MAIL_CONTEXT))
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Wood Corner",
                "email": "wood.corner26@example.com",
                "phone": "(623)-853-7197",
                "website": "http://www.wood-corner.com",
            }
        )

    def test_value_to_html_with_website_and_phone(self):
        Contact = self.env["ir.qweb.field.contact"]
        result = Contact.value_to_html(self.partner, {"fields": ["phone", "website"]})
        self.assertIn('itemprop="website"', result)
        self.assertIn(self.partner.website, result)
        self.assertIn('itemprop="telephone"', result)
        self.assertIn(self.partner.phone, result)
        self.assertNotIn('itemprop="email"', result)

    def test_value_to_html_without_phone(self):
        Contact = self.env["ir.qweb.field.contact"]
        result = Contact.value_to_html(self.partner, {"fields": ["name", "website"]})
        self.assertIn('itemprop="website"', result)
        self.assertIn(self.partner.website, result)
        self.assertNotIn(self.partner.phone, result)
        self.assertIn(
            'itemprop="telephone"',
            result,
            "Empty telephone itemprop should be added to prevent issue with iOS Safari",
        )


class TestQwebFieldOne2Many(common.TransactionCase):
    def value_to_html(self, value, options=None):
        options = options or {}
        return self.env["ir.qweb.field.one2many"].value_to_html(value, options)

    def test_one2many_empty(self):
        partner = self.env["res.partner"].create({"name": "Test Parent"})
        self.assertFalse(self.value_to_html(partner.child_ids))

    def test_one2many_with_values(self):
        parent = self.env["res.partner"].create({"name": "Parent"})
        self.env["res.partner"].create({"name": "Child", "parent_id": parent.id})
        self.assertEqual(self.value_to_html(parent.child_ids), "Parent, Child")


class TestQwebFieldMany2Many(common.TransactionCase):
    def value_to_html(self, value, options=None):
        options = options or {}
        return self.env["ir.qweb.field.many2many"].value_to_html(value, options)

    def test_many2many_empty(self):
        user = self.env["res.users"].create(
            {
                "name": "UserTest",
                "login": "usertest@example.com",
                "group_ids": None,
            }
        )
        self.assertFalse(self.value_to_html(user.group_ids))

    def test_many2many_with_values(self):
        user = self.env["res.users"].create(
            {
                "name": "User2",
                "login": "user2@example.com",
            }
        )
        self.assertEqual(
            self.value_to_html(user.all_group_ids[:2].sorted()),
            "Role / User, Technical Features",
        )


class TestQwebFieldMany2One(common.TransactionCase):
    def value_to_html(self, value, options=None):
        options = options or {}
        return self.env["ir.qweb.field.many2one"].value_to_html(value, options)

    def test_many2one_empty(self):
        partner = self.env["res.partner"].create({"name": "Lonely"})
        self.assertFalse(self.value_to_html(partner.parent_id))

    def test_many2one_with_value(self):
        parent = self.env["res.partner"].create({"name": "BigBoss"})
        child = self.env["res.partner"].create(
            {"name": "Minion", "parent_id": parent.id}
        )
        self.assertEqual(self.value_to_html(child.parent_id), "BigBoss")


class TestQwebFieldHtml(common.TransactionCase):
    def value_to_html(self, value, options=None):
        return self.env["ir.qweb.field.html"].value_to_html(value, options or {})

    def test_html_falsy_values(self):
        """QF-C1: falsy html values must render empty, not the literal 'False'/'None'."""
        self.assertEqual(self.value_to_html(False), "")
        self.assertEqual(self.value_to_html(None), "")
        self.assertEqual(self.value_to_html(""), "")

    def test_html_value_passthrough(self):
        self.assertEqual(self.value_to_html("<p>hi</p>"), "<p>hi</p>")


# Payload reused across the escaping regression tests below.
XSS_NAME = '<script>alert("xss")</script>'
# After HTML-escaping, none of these substrings may appear verbatim; the
# escaped form (&lt;script&gt; / &#34; or &quot;) must appear instead.
XSS_RAW_FRAGMENTS = ("<script>", '"xss"')


class TestQwebFieldEscaping(common.TransactionCase):
    """QF-T1: per-converter escaping/XSS regression tests.

    Pin the invariant that every converter building ``Markup`` from untrusted
    data routes it through ``escape``/``nl2br``/``%``/``.format``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, **DISABLED_MAIL_CONTEXT))

    def _assert_escaped(self, rendered):
        """Assert no raw XSS fragment survived and the value was escaped."""
        rendered = str(rendered)
        for raw in XSS_RAW_FRAGMENTS:
            self.assertNotIn(
                raw, rendered, f"unescaped {raw!r} leaked into {rendered!r}"
            )
        self.assertIn("&lt;script&gt;", rendered)

    def test_text_escapes(self):
        result = self.env["ir.qweb.field.text"].value_to_html(XSS_NAME, {})
        self._assert_escaped(result)

    def test_selection_escapes(self):
        # Selection labels are developer-defined but must be escaped regardless.
        result = self.env["ir.qweb.field.selection"].value_to_html(
            "key", {"selection": {"key": XSS_NAME}}
        )
        self._assert_escaped(result)

    def test_many2one_escapes(self):
        parent = self.env["res.partner"].create({"name": XSS_NAME})
        child = self.env["res.partner"].create(
            {"name": "Child", "parent_id": parent.id}
        )
        result = self.env["ir.qweb.field.many2one"].value_to_html(child.parent_id, {})
        self._assert_escaped(result)

    def test_many2many_escapes(self):
        parent = self.env["res.partner"].create({"name": "Parent"})
        self.env["res.partner"].create({"name": XSS_NAME, "parent_id": parent.id})
        result = self.env["ir.qweb.field.many2many"].value_to_html(parent.child_ids, {})
        self._assert_escaped(result)

    def test_one2many_escapes(self):
        parent = self.env["res.partner"].create({"name": "Parent"})
        self.env["res.partner"].create({"name": XSS_NAME, "parent_id": parent.id})
        result = self.env["ir.qweb.field.one2many"].value_to_html(parent.child_ids, {})
        self._assert_escaped(result)

    def test_contact_escapes(self):
        partner = self.env["res.partner"].create({"name": XSS_NAME})
        result = self.env["ir.qweb.field.contact"].value_to_html(
            partner, {"fields": ["name"]}
        )
        self._assert_escaped(result)

    def test_monetary_escapes_currency_symbol(self):
        # A hostile currency symbol must not break out of the markup template.
        currency = self.env["res.currency"].create(
            {
                "name": "XSS",
                "symbol": '"><script>alert(1)</script>',
                "rounding": 0.01,
            }
        )
        result = self.env["ir.qweb.field.monetary"].value_to_html(
            1000.0, {"display_currency": currency}
        )
        rendered = str(result)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_image_url_escapes(self):
        # The URL is interpolated into an attribute via ``%`` and must not break out.
        result = self.env["ir.qweb.field.image_url"].value_to_html(
            'http://example.com/"><script>alert(1)</script>', {}
        )
        rendered = str(result)
        self.assertNotIn('"><script>', rendered)
        self.assertNotIn("<script>", rendered)
        # Attribute-breakout quote is neutralised.
        self.assertIn("&#34;", rendered)

    def test_image_renders_escaped_data_uri(self):
        # A valid 1x1 PNG; the data URI must land safely inside the src attribute.
        png_b64 = (
            b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4n"
            b"GP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
        )
        result = self.env["ir.qweb.field.image"].value_to_html(png_b64, {})
        rendered = str(result)
        self.assertTrue(rendered.startswith('<img src="data:image/png;base64,'))
        self.assertTrue(rendered.endswith('">'))

    def test_barcode_escapes_value_in_alt(self):
        # The barcode value flows into the ``alt`` attribute; lxml must escape it.
        hostile = 'a"<script>'
        result = self.env["ir.qweb.field.barcode"].value_to_html(
            hostile, {"symbology": "Code128"}
        )
        rendered = str(result)
        self.assertNotIn('"<script>', rendered)
        self.assertNotIn("<script>", rendered)

    def test_barcode_non_ascii_escapes(self):
        # Non-ascii values fall through to nl2br, which escapes.
        result = self.env["ir.qweb.field.barcode"].value_to_html(
            XSS_NAME + "\N{SNOWMAN}", {}
        )
        self._assert_escaped(result)


class TestQwebFieldAttributes(common.TransactionCase):
    """QF-T2: branding metadata (``data-oe-*``) produced by ``attributes()``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, **DISABLED_MAIL_CONTEXT))
        cls.partner = cls.env["res.partner"].create({"name": "Branding Co"})

    def test_attributes_returns_empty_without_branding_or_translate(self):
        result = self.env["ir.qweb.field"].attributes(
            self.partner,
            "name",
            {"inherit_branding": False, "translate": False},
        )
        self.assertEqual(result, {})

    def test_attributes_branding_dict(self):
        result = self.env["ir.qweb.field"].attributes(
            self.partner,
            "name",
            {
                "inherit_branding": True,
                "translate": False,
                "type": "char",
                "expression": "record.name",
            },
        )
        self.assertEqual(result["data-oe-model"], "res.partner")
        self.assertEqual(result["data-oe-id"], self.partner.id)
        self.assertEqual(result["data-oe-field"], "name")
        self.assertEqual(result["data-oe-type"], "char")
        self.assertEqual(result["data-oe-expression"], "record.name")

    def test_attributes_readonly_flag(self):
        # ``id`` is a readonly field, so the readonly marker must be present.
        result = self.env["ir.qweb.field"].attributes(
            self.partner,
            "id",
            {"inherit_branding": True, "translate": False},
        )
        self.assertEqual(result["data-oe-readonly"], 1)
