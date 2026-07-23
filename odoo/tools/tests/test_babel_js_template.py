"""Regression tests for template-string term extraction in the JS extractor.

A ``_t("...")`` call inside a ``${ ... }`` template-string expression must be
extracted even when the string contains an escaped quote; a previous
single-vs-two-character escape bug silently dropped such terms from the POT.
"""

import io
import unittest

from odoo.tools.babel_extractors.javascript_extractor import extract_javascript

_OPTS = {"jsx": True, "template_string": True, "parse_template_string": True}


def _extract(src):
    return list(extract_javascript(io.BytesIO(src.encode()), {"_t": None}, [], _OPTS))


class TestTemplateStringExtraction(unittest.TestCase):
    def test_plain_term_in_template_expression(self):
        results = _extract("const a = `${ _t('hello') }`;")
        self.assertEqual([(r[1], r[2]) for r in results], [("_t", "hello")])

    def test_escaped_quote_does_not_drop_term(self):
        # the ``\'`` must not be treated as the string's closing quote
        results = _extract(r"""const a = `${ _t('don\'t drop me') }`;""")
        self.assertEqual([r[2] for r in results], ["don't drop me"])

    def test_escaped_double_quote_in_double_quoted_string(self):
        results = _extract(r"""const a = `${ _t("a\"b") }`;""")
        self.assertEqual([r[2] for r in results], ['a"b'])

    def test_escaped_backslash_before_quote_still_closes(self):
        # ``\\`` is an escaped backslash, so the following quote DOES close
        results = _extract(r"""const a = `${ _t("path\\") }`;""")
        self.assertEqual([r[2] for r in results], ["path\\"])


if __name__ == "__main__":
    unittest.main()
