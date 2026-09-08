import logging

from lxml import etree

from odoo.tests.common import BaseCase

from . import _pretty_xml, _xml_sweep
from .lint_case import LintCase

_logger = logging.getLogger(__name__)


class TestOpaqueFieldPreservesValue(BaseCase):
    def _field_value(self, xml: str) -> str:
        record = etree.fromstring(xml.encode())
        field = record.find("field")
        formatted = "\n".join(_pretty_xml._format_element(record, 0))
        reparsed = etree.fromstring(formatted.encode())
        reparsed_field = reparsed.find("field")
        original = etree.tostring(field, encoding="unicode")
        result = etree.tostring(reparsed_field, encoding="unicode")
        return original[original.index(">") + 1 : original.rindex("<")], result[
            result.index(">") + 1 : result.rindex("<")
        ]

    def test_single_line_html_field_is_not_split_across_lines(self):
        xml = (
            '<record id="x" model="mail.template">'
            '<field name="body_html" type="html">'
            "<p>Hello <t t-out=\"object.name or ''\"></t></p>"
            "</field></record>"
        )
        original, result = self._field_value(xml)
        self.assertNotIn("\n", result, "a single-line field must stay single-line")
        self.assertEqual(result.replace(" />", "></t>"), original)

    def test_overlong_single_line_html_field_wraps_attributes_not_content(self):
        xml = (
            '<record id="x" model="mail.template">'
            '<field name="body_html" type="html">'
            '<p>Hello <t t-out="object.name or a_much_longer_expression_here"></t></p>'
            "</field></record>"
        )
        original, result = self._field_value(xml)
        self.assertNotIn("\n", result, "wrapping attributes must not touch the content")
        self.assertEqual(result.replace(" />", "></t>"), original)

    def test_genuinely_multi_line_arch_still_reindents(self):
        xml = (
            '<record id="x" model="ir.ui.view">'
            '<field name="arch" type="xml">\n'
            "    <form>\n"
            '        <field name="name"/>\n'
            "    </form>\n"
            "</field></record>"
        )
        record = etree.fromstring(xml.encode())
        lines = _pretty_xml._format_element(record, 0)
        formatted = "\n".join(lines)
        self.assertIn("\n", formatted)
        reparsed = etree.fromstring(formatted.encode())
        self.assertIsNotNone(reparsed.find("field/form/field"))


class PrettyXmlLinter(LintCase):
    def test_xml_formatting(self):
        sweep = _xml_sweep.formatter_sweep()
        _logger.info("checked %s XML data files", sweep.checked)
        self.assertTrue(sweep.checked, "the scan reached no XML data files at all")
        self.assert_ratchet(
            sweep.changed,
            "lint_xml_unformatted",
            "XML data file(s) not in canonical format",
            "Format them, then bank the new floor:\n"
            "    python odoo/addons/test_lint/tests/_pretty_xml.py odoo/addons addons",
        )

    def test_no_data_file_is_unparseable(self):
        sweep = _xml_sweep.formatter_sweep()
        self.assertFalse(
            sweep.unparseable,
            f"{len(sweep.unparseable)} file(s) selected as XML data do not parse. "
            f"Either they are fixtures that do not belong in the selection, or "
            f"they are broken:\n  " + "\n  ".join(sweep.unparseable),
        )
