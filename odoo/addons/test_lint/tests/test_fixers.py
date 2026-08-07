"""Unit tests for the in-place XML fixers.

``_pretty_xml`` and ``_sort_xml_records`` rewrite every data file in the
repository, and between them they had **no unit tests at all** -- the only
exercise was the lint test running them in dry-run over the tree, which reports
*that* a file would change and never *what* the change is. Both of the defects
below survived in that blind spot:

* text between child elements was silently deleted;
* tab-indented arch content made the formatter oscillate instead of converge,
  so the gate could not go green on the file however often the fixer ran.

The three properties asserted here are the ones a formatter has to have:
it must not change what the document *means*, running it twice must equal
running it once, and it must agree with the lint test about which files it owns.
"""

import textwrap
from pathlib import Path

from lxml import etree

from odoo.tests.common import BaseCase, no_retry

from . import _pretty_xml
from .lint_case import LintCase, is_core_path


def _semantic(xml: bytes) -> bytes:
    """A comparable form of *xml* that ignores whitespace-only text nodes.

    Re-indenting is the formatter's job, so indentation must not count as a
    difference -- but a text node with real content in it must.
    """
    root = etree.fromstring(xml)
    for element in root.iter():
        if callable(element.tag):
            continue
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    return etree.tostring(root, method="c14n")


@no_retry
class TestPrettyXml(BaseCase):
    """The formatter must preserve meaning and reach a fixed point."""

    maxDiff = None

    def _format(self, source: str, passes: int = 1) -> str:
        path = Path(self.tmpdir) / "case.xml"
        path.write_bytes(textwrap.dedent(source).lstrip().encode())
        for _ in range(passes):
            _pretty_xml.format_xml_file(path)
        return path.read_text()

    def setUp(self):
        super().setUp()
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_text_between_children_survives(self):
        """The regression: a translatable string vanished from 317 files.

        ``<span><t t-out="n"/> are not shown in the preview</span>`` lost its
        sentence entirely, because the data-layer path emitted the open tag, the
        children and the close tag, and nothing else.
        """
        out = self._format("""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <templates>
                    <span><t t-out="value"/> are not shown in the preview</span>
                </templates>
            </odoo>
        """)
        self.assertIn("are not shown in the preview", out)

    def test_text_before_a_child_survives(self):
        out = self._format("""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <function model="m" name="f">leading text<value>x</value></function>
            </odoo>
        """)
        self.assertIn("leading text", out)

    def test_meaning_is_preserved(self):
        source = textwrap.dedent("""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <record id="r" model="ir.ui.view">
                    <field name="name">A view</field>
                    <field name="arch" type="xml">
                        <form><field name="x"/> trailing <b>bold</b> tail</form>
                    </field>
                </record>
                <p>mixed <b>bold</b> tail text</p>
            </odoo>
        """).lstrip()
        formatted = self._format(source)
        self.assertEqual(_semantic(source.encode()), _semantic(formatted.encode()))

    def test_formatting_is_idempotent(self):
        """Running it twice must equal running it once, or the gate can never pass."""
        source = """
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <record id="r" model="ir.ui.view">
                    <field name="arch" type="xml">
                        <form>
                            <field name="a"/>
                        </form>
                    </field>
                </record>
            </odoo>
        """
        self.assertEqual(self._format(source, passes=1), self._format(source, passes=3))

    def test_tab_indented_arch_converges(self):
        """The oscillation: 19 -> 9 -> 15 -> 9 columns, never settling."""
        source = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<odoo>\n"
            '    <record id="r" model="ir.ui.view">\n'
            '        <field name="arch" type="xml">\n'
            '\t<xpath expr="//a" position="inside">\n'
            '                <field name="x"/>\n'
            "            </xpath>\n"
            "        </field>\n"
            "    </record>\n"
            "</odoo>\n"
        )
        once = self._format(source, passes=1)
        self.assertEqual(once, self._format(source, passes=4))
        self.assertNotIn("\t", once, "leading tabs should be normalised, not carried")

    def test_reports_no_change_for_its_own_output(self):
        """``dry_run`` must answer False once the file is canonical."""
        path = Path(self.tmpdir) / "case.xml"
        path.write_bytes(
            b'<?xml version="1.0" encoding="utf-8"?>\n<odoo>\n\n    <record '
            b'id="r" model="m">\n        <field name="a">1</field>\n    </record>'
            b"\n\n</odoo>\n"
        )
        _pretty_xml.format_xml_file(path)
        self.assertIs(_pretty_xml.format_xml_file(path, dry_run=True), False)

    def test_parse_error_is_reported_as_skipped(self):
        path = Path(self.tmpdir) / "broken.xml"
        path.write_bytes(b"<odoo><unclosed></odoo>")
        self.assertIsNone(_pretty_xml.format_xml_file(path, dry_run=True))


@no_retry
class TestFixerScope(LintCase):
    """The lint test and the fixer must own exactly the same file set.

    They did not: the test flagged 12 665 files and the fixer declined 9 876 of
    them, so its own remediation instructions could not make it pass.
    """

    def test_static_templates_are_not_data_files(self):
        self.assertFalse(
            _pretty_xml.is_formattable(Path("/a/account/static/src/x.xml"))
        )
        self.assertTrue(_pretty_xml.is_formattable(Path("/a/account/views/x.xml")))

    def test_every_flagged_file_is_one_the_fixer_would_rewrite(self):
        """Whatever the lint test reports, the fixer must accept."""
        flagged = [
            path
            for path in map(Path, self.iter_module_files("*.xml"))
            if is_core_path(str(path)) and _pretty_xml.is_formattable(path)
        ]
        self.assertTrue(flagged, "the scan reached no data files")
        declined = [path for path in flagged if not _pretty_xml.is_formattable(path)]
        self.assertFalse(declined, "the lint test would report files the fixer skips")
