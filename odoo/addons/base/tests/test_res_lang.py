import locale

from odoo import tools
from odoo.exceptions import UserError
from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base.models.res_lang import LangData, format_number, intersperse


class TestFormatNumberPure(BaseCase):
    """format_number is pure (registry-free): all locale conventions come from
    the LangData argument, so it is DB-free unit-testable. (W2)"""

    EN = LangData(
        {"id": 1, "decimal_point": ".", "thousands_sep": ",", "grouping": "[3,0]"}
    )
    EU = LangData(
        {"id": 2, "decimal_point": ",", "thousands_sep": ".", "grouping": "[3,0]"}
    )
    IN = LangData(
        {"id": 3, "decimal_point": ".", "thousands_sep": ",", "grouping": "[3,2,0]"}
    )

    def test_float_specs(self):
        self.assertEqual(format_number("%.2f", 1234.5, self.EN), "1234.50")
        self.assertEqual(
            format_number("%.2f", 1234.5, self.EN, grouping=True), "1,234.50"
        )
        self.assertEqual(
            format_number("%.2f", -1234.5, self.EN, grouping=True), "-1,234.50"
        )
        self.assertEqual(
            format_number("%.2f", 1234.5, self.EU, grouping=True), "1.234,50"
        )
        self.assertEqual(format_number("%.2f", 1234.5, self.EU), "1234,50")

    def test_int_specs(self):
        self.assertEqual(
            format_number("%d", 1234567, self.EN, grouping=True), "1,234,567"
        )
        self.assertEqual(format_number("%d", 1234567, self.EN), "1234567")
        self.assertEqual(
            format_number("%d", 12345678, self.IN, grouping=True), "1,23,45,678"
        )

    def test_scientific_notation_not_grouped(self):
        self.assertEqual(format_number("%g", 1e20, self.EN, grouping=True), "1e+20")
        self.assertEqual(
            format_number("%e", 1e20, self.EN, grouping=True), "1.000000e+20"
        )
        self.assertEqual(format_number("%g", 1234.5, self.EN, grouping=True), "1,234.5")

    def test_bad_spec_raises(self):
        with self.assertRaises(ValueError):
            format_number("d", 1234, self.EN)
        with self.assertRaises(ValueError):
            format_number("", 1234, self.EN)


class test_res_lang(TransactionCase):
    def test_00_intersperse(self):
        assert intersperse("", []) == ("", 0)
        assert intersperse("0", []) == ("0", 0)
        assert intersperse("012", []) == ("012", 0)
        assert intersperse("1", []) == ("1", 0)
        assert intersperse("12", []) == ("12", 0)
        assert intersperse("123", []) == ("123", 0)
        assert intersperse("1234", []) == ("1234", 0)
        assert intersperse("123456789", []) == ("123456789", 0)
        assert intersperse("&ab%#@1", []) == ("&ab%#@1", 0)

        assert intersperse("0", []) == ("0", 0)
        assert intersperse("0", [1]) == ("0", 0)
        assert intersperse("0", [2]) == ("0", 0)
        assert intersperse("0", [200]) == ("0", 0)

        assert intersperse("12345678", [1], ".") == ("1234567.8", 1)
        assert intersperse("12345678", [1], ".") == ("1234567.8", 1)
        assert intersperse("12345678", [2], ".") == ("123456.78", 1)
        assert intersperse("12345678", [2, 1], ".") == ("12345.6.78", 2)
        assert intersperse("12345678", [2, 0], ".") == ("12.34.56.78", 3)
        assert intersperse("12345678", [-1, 2], ".") == ("12345678", 0)
        assert intersperse("12345678", [2, -1], ".") == ("123456.78", 1)
        assert intersperse("12345678", [2, 0, 1], ".") == ("12.34.56.78", 3)
        assert intersperse("12345678", [2, 0, 0], ".") == ("12.34.56.78", 3)
        assert intersperse("12345678", [2, 0, -1], ".") == ("12.34.56.78", 3)
        assert intersperse("12345678", [3, 3, 3, 3], ".") == ("12.345.678", 2)

        assert intersperse("abc1234567xy", [2], ".") == ("abc1234567.xy", 1)
        assert intersperse("abc1234567xy8", [2], ".") == (
            "abc1234567x.y8",
            1,
        )  # ... w.r.t. here.
        assert intersperse("abc12", [3], ".") == ("abc12", 0)
        assert intersperse("abc12", [2], ".") == ("abc12", 0)
        assert intersperse("abc12", [1], ".") == ("abc1.2", 1)

    def test_format_scientific_notation_not_grouped(self):
        """RL-L2: format() must not inject a thousands separator into the
        exponent of scientific-notation output when grouping=True."""
        lang = self.env["res.lang"]._activate_lang("en_US")
        # %g / %G emit bare scientific notation; the exponent must stay intact.
        self.assertEqual(lang.format("%g", 1e20, grouping=True), "1e+20")
        self.assertEqual(lang.format("%g", 1e7, grouping=True), "1e+07")
        self.assertEqual(lang.format("%G", 1e20, grouping=True), "1E+20")
        # %e / %E emit a mantissa decimal point; only the exponent must be safe.
        self.assertEqual(lang.format("%e", 1e20, grouping=True), "1.000000e+20")
        self.assertEqual(lang.format("%E", 1e20, grouping=True), "1.000000E+20")
        # Regression guard: plain (non-scientific) float/int output still groups.
        self.assertEqual(lang.format("%.2f", 1234.5, grouping=True), "1,234.50")
        self.assertEqual(lang.format("%g", 1234.5, grouping=True), "1,234.5")
        self.assertEqual(lang.format("%d", 1234567, grouping=True), "1,234,567")

    def test_format_indian_grouping(self):
        """RL-T1: Indian grouping [3,2,0] groups as 1,23,45,678."""
        lang = self.env["res.lang"]._activate_lang("en_US")
        lang.grouping = "[3,2,0]"
        self.assertEqual(lang.format("%d", 12345678, grouping=True), "1,23,45,678")
        self.assertEqual(
            lang.format("%.2f", 12345678.0, grouping=True), "1,23,45,678.00"
        )

    def test_format_negative_grouping(self):
        """RL-T1: negative values keep the minus sign and group correctly."""
        lang = self.env["res.lang"]._activate_lang("en_US")
        self.assertEqual(lang.format("%.2f", -1234.5, grouping=True), "-1,234.50")
        self.assertEqual(lang.format("%d", -1234567, grouping=True), "-1,234,567")

    def test_format_bad_spec_raises(self):
        """RL-T1: a spec not starting with '%' raises ValueError."""
        lang = self.env["res.lang"]._activate_lang("en_US")
        with self.assertRaises(ValueError):
            lang.format("d", 1234)
        with self.assertRaises(ValueError):
            lang.format("", 1234)

    def test_create_lang_grouping_normalisation(self):
        """RL-T2: an out-of-Selection libc grouping coerces to '[3,0]'."""
        ResLang = self.env["res.lang"]
        grouping_options = {v for v, _label in ResLang._fields["grouping"].selection}
        # The normalisation strips spaces; a recognised value is kept as-is.
        normalised = str([3, 0]).replace(" ", "")
        self.assertEqual(normalised, "[3,0]")
        self.assertIn(normalised, grouping_options)
        # An unexpected libc grouping (e.g. [4, 0]) is not a Selection value and
        # must fall back to the default '[3,0]'.
        weird = str([4, 0]).replace(" ", "")
        self.assertNotIn(weird, grouping_options)
        coerced = weird if weird in grouping_options else "[3,0]"
        self.assertEqual(coerced, "[3,0]")

    @mute_logger("odoo.addons.base.models.res_lang")
    def test_create_lang_resets_process_locale(self):
        """RL-C1: _create_lang mutates the process-global locale in a serialized
        window (_LOCALE_LOCK) and must always restore it, even when the requested
        locale is unavailable on the platform."""
        tools.translate.resetlocale()
        before = locale.setlocale(locale.LC_ALL)
        lang = self.env["res.lang"]._create_lang("xx_XX", "Locale Window Test")
        self.assertEqual(
            locale.setlocale(locale.LC_ALL),
            before,
            "_create_lang must reset the process locale after reading it",
        )
        self.assertTrue(lang.active)
        self.assertEqual(lang.code, "xx_XX")
        self.assertTrue(lang.date_format)
        self.assertTrue(lang.time_format)
        self.assertIn(
            lang.grouping,
            {v for v, _label in lang._fields["grouping"].selection},
        )

    def test_copy_lang_codes_are_url_safe_and_unique(self):
        """RL-B3: copying a language must not push the translated '(copy)' suffix
        into 'code' (frozen by write()) or 'url_code' (routing-facing, unique):
        both get an untranslated URL-safe suffix with a counter, while 'name'
        keeps the translated suffix."""
        lang = self.env["res.lang"]._activate_lang("en_US")
        copy1 = lang.copy()
        self.assertEqual(copy1.name, f"{lang.name} (copy)")
        self.assertEqual(copy1.code, f"{lang.code}_copy")
        self.assertEqual(copy1.url_code, f"{lang.url_code}_copy")
        # A second copy must not collide on the unique code/url_code ('name'
        # must be overridden: it carries its own unique constraint).
        copy2 = lang.copy({"name": "English (US) (second copy)"})
        self.assertEqual(copy2.code, f"{lang.code}_copy2")
        self.assertEqual(copy2.url_code, f"{lang.url_code}_copy2")
        # Values passed through 'default' always win over the suffix logic.
        copy3 = lang.copy({"name": "Xx", "code": "xx_XX", "url_code": "xx"})
        self.assertEqual(copy3.code, "xx_XX")
        self.assertEqual(copy3.url_code, "xx")

    def test_inactive_users_lang_deactivation(self):
        # activate the language en_GB
        language = self.env["res.lang"]._activate_lang("en_GB")

        # assign it to an inactive (new) user
        user = self.env["res.users"].create(
            {
                "name": "Foo",
                "login": "foo@example.com",
                "lang": "en_GB",
                "active": False,
            }
        )

        # make sure it is only used by that user
        self.assertEqual(
            self.env["res.users"]
            .with_context(active_test=False)
            .search([("lang", "=", "en_GB")]),
            user,
        )

        with self.assertRaises(UserError):
            language.active = False

    def test_get_data(self):
        ResLang = self.env["res.lang"]
        en_id = ResLang._activate_lang("en_US").id
        en_url_code = ResLang.browse(en_id).url_code
        fr_id = ResLang._activate_lang("fr_FR").id
        fr_direction = ResLang.browse(fr_id).direction
        fr_data = ResLang._get_data(id=fr_id)
        dummy_data = ResLang._get_data(id=0)

        # test __eq__
        self.env.registry.clear_cache()
        self.assertEqual(ResLang._get_data(id=fr_id), fr_data)
        self.assertEqual(ResLang._get_data(id=0), dummy_data)

        # test __bool__
        # data for an active language
        self.assertTrue(ResLang._get_data(code="en_US"))
        # data for an inactive language
        self.assertFalse(ResLang._get_data(code="nl_NL"))
        # data for an invalid dummy language
        self.assertFalse(ResLang._get_data(code="dummy"))

        # test dict conversion
        self.assertEqual(
            dict(ResLang._get_data(id=fr_id)),
            ResLang.browse(fr_id).read(ResLang.CACHED_FIELDS)[0],
        )
        self.assertEqual(
            dict(ResLang._get_data(id=0)),
            dict.fromkeys(ResLang.CACHED_FIELDS, False),
        )

        # test performance
        self.env._core.clear_cache()
        self.env.registry.clear_cache()
        # 1 query for res_lang +
        # 1 query for ir_attachment to compute `flag_image_url`
        with self.assertQueryCount(2):
            # get cached field value for an active language
            self.assertEqual(ResLang._get_data(code="en_US").url_code, en_url_code)
            # get another cached field value for another active language
            self.assertEqual(ResLang._get_data(code="fr_FR").direction, fr_direction)
            # get field value for an inactive language
            self.assertEqual(ResLang._get_data(code="nl_NL").direction, False)
            # get field value for a dummy language
            self.assertEqual(ResLang._get_data(code="dummy").direction, False)

        # test programming error
        with self.assertRaises(AttributeError):
            # raise error for querying a not cached field of an active language
            _ = ResLang._get_data(code="en_US").flag_image
        with self.assertRaises(AttributeError):
            # raise error for querying a not cached field of an inactive language
            _ = ResLang._get_data(code="nl_NL").flag_image
        with self.assertRaises(AttributeError):
            # raise error for querying a not cached field of the dummy language
            _ = ResLang._get_data(code="dummy").flag_image

    def test_lang_url_code_shortening(self):
        # Setup and initial checks
        ResLang = self.env["res.lang"]
        es_ES = self.env.ref("base.lang_es")
        self.assertFalse(es_ES.active)
        self.assertEqual(es_ES.url_code, "es_ES")
        es_419 = self.env.ref("base.lang_es_419")
        self.assertFalse(es_419.active)
        self.assertEqual(es_419.url_code, "es")

        # Activating es_ES should give it the url_code 'es' (short version) and
        # es_419 should have its url_code changed from 'es' to 'es_419'
        ResLang._activate_lang("es_ES")
        self.assertEqual(es_419.url_code, "es_419")
        self.assertEqual(es_ES.url_code, "es")
        # Activating es_419 should not set it's url_code back to 'es'
        ResLang._activate_lang("es_419")
        self.assertEqual(es_419.url_code, "es_419")
        self.assertEqual(es_ES.url_code, "es")
        # Disabling both 'es' languages and activating 'es_419' should set its
        # url_code back to 'es' since that short version is now 'available'
        (es_419 + es_ES).write({"active": False})
        ResLang._activate_lang("es_419")
        self.assertEqual(es_419.url_code, "es")
        self.assertEqual(es_ES.url_code, "es_ES")

        # Now, special case if one day a lang receive a short code as default
        # `code`, it's not the case as of today but there is plan to make it
        # happen for `es_419`, the code is already ready for it.
        self.env.cr.execute(
            f""" UPDATE res_lang SET code = 'es' where id = {es_419.id}"""
        )
        self.env.invalidate_all()
        self.assertEqual(es_419.code, "es")
        (es_419 + es_ES).write({"active": False})
        ResLang._activate_lang("es_419")
        self.assertEqual(es_419.url_code, "es")
        self.assertEqual(es_ES.url_code, "es_ES")
        es_419.active = False
        ResLang._activate_lang("es_ES")
        self.assertEqual(es_419.url_code, "es")
        # es_ES can't have its url_code shortened because there is no
        # possibility to replace 'es' url_code from 'es_419' if we change its
        # code from 'es_419' to 'es' in the future
        self.assertEqual(es_ES.url_code, "es_ES")

        # Another special case, /my is reserved to portal controller
        my_MM = ResLang._activate_lang("my_MM")
        self.assertEqual(my_MM.url_code, "mya")
