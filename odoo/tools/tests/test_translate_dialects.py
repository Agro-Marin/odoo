"""The two translation dialects, and the parser the round-trip uses.

``translate_xml_node`` used to take a ``parse`` argument that all three call
sites supplied and the body never read. Deleting it rather than honouring it is
the point of ``test_html_is_the_round_trip_parser_on_purpose`` below: translators
write ``<br>``, so parsing the translated fragment as XML turns an ordinary
translation into an ``XMLSyntaxError``.
"""

import unittest

from odoo.tools.translate import (
    FIELD_TRANSLATE,
    TranslationDialect,
    html_translate,
    xml_translate,
)


class TestTranslationDialect(unittest.TestCase):
    def test_a_dialect_is_callable_like_the_function_it_replaced(self):
        """`callable(field.translate)` is how the ORM tells a dialect apart."""
        for dialect in (xml_translate, html_translate):
            with self.subTest(dialect=dialect.name):
                self.assertTrue(callable(dialect))
                self.assertIsInstance(dialect, TranslationDialect)

    def test_round_trip_translates(self):
        self.assertEqual(
            xml_translate(lambda term: term.upper(), "<div>hi</div>"),
            "<div>HI</div>",
        )
        self.assertEqual(
            html_translate(lambda term: term.upper(), "<p>hi</p>"),
            "<p>HI</p>",
        )

    def test_the_adapter_asymmetry_is_declared_not_discovered(self):
        """Only the XML dialect can adapt a term to a changed structure.

        This was previously discoverable only as a `hasattr` in the ORM.
        """
        self.assertIsNotNone(xml_translate.term_adapter)
        self.assertIsNone(html_translate.term_adapter)

    def test_every_dialect_carries_the_shared_members(self):
        for dialect in (xml_translate, html_translate):
            with self.subTest(dialect=dialect.name):
                self.assertEqual(dialect.get_text_content("<b>a  b</b>"), "a b")
                self.assertTrue(callable(dialect.term_converter))
                self.assertTrue(callable(dialect.is_text))

    def test_field_translate_still_resolves_both_ways(self):
        """`ir.model.fields` looks a dialect up by equality, and back by name."""
        self.assertIs(FIELD_TRANSLATE["xml_translate"], xml_translate)
        self.assertEqual(
            next(k for k, v in FIELD_TRANSLATE.items() if v == html_translate),
            "html_translate",
        )

    def test_a_dialect_is_hashable(self):
        self.assertEqual(
            len({xml_translate, html_translate, xml_translate}),
            2,
        )


class TestRoundTripParser(unittest.TestCase):
    def test_html_is_the_round_trip_parser_on_purpose(self):
        """A translation may contain HTML that is not well-formed XML.

        ``<br>`` is the everyday case. Re-parsing the translated fragment
        strictly would raise instead of translating, which is why the deleted
        ``parse`` argument must not be reinstated.
        """
        result = xml_translate(
            lambda term: "<b>bold<br>unclosed</b>" if "hello" in term else None,
            "<form><div>hello</div></form>",
        )
        self.assertEqual(result, "<form><div><b>bold<br/>unclosed</b></div></form>")

    def test_translate_xml_node_takes_no_parse_argument(self):
        from odoo.tools.translate import translate_xml_node

        self.assertNotIn("parse", translate_xml_node.__code__.co_varnames[:3])


if __name__ == "__main__":
    unittest.main()
