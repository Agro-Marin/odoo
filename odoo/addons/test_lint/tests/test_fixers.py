"""Unit and property tests for the in-place XML fixers.

``_pretty_xml`` and ``_sort_xml_records`` rewrite every data file in the
repository, and between them they had **no unit tests at all** -- the only
exercise was the lint test running them in dry-run over the tree, which reports
*that* a file would change and never *what* the change is. Every defect below
survived in that blind spot:

* text between child elements was silently deleted;
* tab-indented arch content made the formatter oscillate instead of converge;
* a namespaced tag was written back in Clark notation, ``<{urn:…}Invoice>``,
  and its ``xmlns`` declarations dropped -- 268 files parsed before a run and
  did not parse after it;
* an element with no attributes and a long text lost its content *and* its
  closing tag, because the line-wrapping loop is driven by the attribute list;
* a character reference in an attribute came back as a literal newline, which
  attribute-value normalisation then turns into a space;
* a record naming the same field twice came back with one of them deleted.

Four of those six are things no snippet-sized example was ever going to show.
They were found by running the fixers over the **whole repository** and asking
whether the result still says the same thing -- which is what
:class:`TestFixersOverTheRepository` does, so the next one is found the same way
and not by a report of a missing string in production.
"""

import tempfile
import textwrap
from pathlib import Path

from lxml import etree

from odoo.tests.common import BaseCase, no_retry

from . import _pretty_xml, _sort_xml_records
from .lint_case import LintCase, core_root, core_xml_files

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)

DECLINED_BY_THE_FORMATTER: list[str] = []


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


def _shape(xml: bytes) -> list[tuple]:
    """Every element of *xml* as ``(depth, qualified tag, sorted attributes)``.

    Attribute *values* are compared exactly, which is what catches a character
    reference turning into the whitespace it stands for. Sibling order is not,
    because reordering is precisely what the record sorter is for.
    """
    root = etree.fromstring(xml)
    out = []

    def walk(element, depth):
        if not callable(element.tag):
            out.append((depth, element.tag, tuple(sorted(element.attrib.items()))))
        for child in element:
            walk(child, depth + 1)

    walk(root, 0)
    return sorted(out)


def _words(xml: bytes) -> list[str]:
    """Every word of every text node in *xml*, sorted.

    The counterpart to :func:`_shape`, and deliberately a *different* reduction
    from the one the formatter checks itself against: a test that reuses the
    implementation's own notion of "the same" can only ever agree with it. This
    one answers the question that matters -- is any word gone -- and does it
    without caring where the line breaks fell.
    """
    root = etree.fromstring(xml)
    return sorted(
        word
        for element in root.iter()
        for chunk in ((element.text or ""), (element.tail or ""))
        for word in chunk.split()
    )


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

    def test_a_stray_column_does_not_multiply_the_indentation(self):
        """The other divergence, and the one a synthetic case nearly missed.

        Nesting used to be ``(spaces - base) // step`` with ``step`` the
        *smallest* indent seen above the base. One continuation line a single
        column deeper -- the wrapped attribute below -- made ``step`` 1, so
        every real level of nesting multiplied by four and the file grew its
        own indentation without bound, pass after pass.
        """
        source = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<odoo>\n"
            '    <record id="r" model="ir.ui.view">\n'
            '        <field name="arch" type="xml">\n'
            "            <form>\n"
            '             <field name="a"\n'
            '                    string="wrapped"/>\n'
            "                <group>\n"
            '                    <field name="b"/>\n'
            "                </group>\n"
            "            </form>\n"
            "        </field>\n"
            "    </record>\n"
            "</odoo>\n"
        )
        once = self._format(source, passes=1)
        self.assertEqual(once, self._format(source, passes=4), "must converge")
        widest = max(len(line) - len(line.lstrip(" ")) for line in once.splitlines())
        self.assertLess(widest, 40, f"indentation ran away:\n{once}")

    def test_a_namespaced_document_survives(self):
        """``elem.tag`` is ``{uri}local`` and the declarations are not in ``attrib``.

        Writing the tag straight out gives ``<{urn:B}simpleAddress>``, which is
        not well-formed; keeping the prefix but not the ``xmlns`` gives an
        undefined-prefix error instead. Both happened, on shipped data.
        """
        out = self._format("""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <template id="t" xmlns:base="urn:B">
                    <base:simpleAddress key="v">hello</base:simpleAddress>
                </template>
            </odoo>
        """)
        self.assertNotIn("{urn:B}", out, "Clark notation is not XML")
        self.assertIn('xmlns:base="urn:B"', out)
        root = etree.fromstring(out.encode())
        self.assertEqual(
            root.find(".//{urn:B}simpleAddress").text.strip(),
            "hello",
        )

    def test_a_long_attribute_less_element_keeps_its_content(self):
        """The wrapping loop is driven by the attribute list.

        With no attributes it ran zero times, and the suffix it was supposed to
        place -- the text *and* the closing tag -- was dropped. Three shipped
        snippet files lost the ``<path>`` of an ``<asset>`` this way.
        """
        long_path = "website/static/src/snippets/s_mega_menu_big_icons/000.scss"
        out = self._format(f"""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <asset id="a" name="n">
                    <path>{long_path}</path>
                </asset>
            </odoo>
        """)
        self.assertIn(long_path, out)
        self.assertIn("</path>", out)
        etree.fromstring(out.encode())

    def test_a_character_reference_in_an_attribute_keeps_its_value(self):
        """A literal newline in an attribute is normalised to a space on reparse.

        So writing one back where the source had ``&#10;`` changes the value --
        silently, and only when the file is next read.
        """
        out = self._format("""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <record id="r" model="m">
                    <field name="c" eval="{&#10;'k': 1&#10;}"/>
                </record>
            </odoo>
        """)
        value = etree.fromstring(out.encode()).find(".//field").get("eval")
        self.assertEqual(value, "{\n'k': 1\n}")

    def test_a_doctype_is_not_dropped(self):
        out = self._format("""
            <?xml version="1.0" encoding="utf-8"?>
            <!DOCTYPE odoo SYSTEM "odoo.dtd">
            <odoo>
                <record id="r" model="m"><field name="a">1</field></record>
            </odoo>
        """)
        self.assertIn('<!DOCTYPE odoo SYSTEM "odoo.dtd">', out)

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

    def test_an_unfaithful_rewrite_is_refused_rather_than_written(self):
        """The safety net, exercised by making the serialiser lie.

        Every defect above was a way of producing a plausible-looking file that
        no longer said the same thing, and in each case the formatter reported
        success. It now compares its own output against the input and declines
        the file when they disagree, so the worst a future one can do is skip.
        """
        path = Path(self.tmpdir) / "case.xml"
        path.write_bytes(
            b'<?xml version="1.0" encoding="utf-8"?>\n<odoo>\n'
            b'    <record id="r" model="m"><field name="a">keep me</field></record>\n'
            b"</odoo>\n"
        )
        original = path.read_bytes()
        real = _pretty_xml._esc_text
        try:
            _pretty_xml._esc_text = lambda value: ""
            self.assertIsNone(_pretty_xml.format_xml_file(path))
        finally:
            _pretty_xml._esc_text = real
        self.assertEqual(path.read_bytes(), original, "the file must be untouched")


@no_retry
class TestSortXmlRecords(BaseCase):
    """The record sorter may reorder; it may not lose anything."""

    maxDiff = None

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _sort(self, source: str) -> bytes:
        path = Path(self.tmpdir) / "case.xml"
        path.write_bytes(textwrap.dedent(source).lstrip().encode())
        _sort_xml_records.sort_xml_file(path)
        return path.read_bytes()

    def test_a_repeated_field_name_keeps_both_elements(self):
        """``hr_holidays``' kanban view, reduced.

        The reordering went through a ``{name: element}`` map, so the second
        ``mode`` was never put back: six fields in, five out, on the script the
        lint gate prints as its remediation.
        """
        out = self._sort("""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <record id="v" model="ir.ui.view">
                    <field name="arch" type="xml"><form/></field>
                    <field name="name">n</field>
                    <field name="mode">primary</field>
                    <field name="mode">extension</field>
                </record>
            </odoo>
        """)
        root = etree.fromstring(out)
        self.assertEqual(len(root.findall(".//field")), 4)
        self.assertEqual(
            [f.text for f in root.findall(".//field[@name='mode']")],
            ["primary", "extension"],
            "repeated names must keep their relative order",
        )

    def test_the_expected_order_of_a_repeated_name_lists_it_twice(self):
        """Otherwise the record can never be made to pass.

        A six-name actual order cannot equal a five-name expected one, so the
        lint test reported the record as out of order for as long as it existed
        -- and the fixer's answer was to delete the difference.
        """
        self.assertEqual(
            _sort_xml_records.expected_field_order(
                ["arch", "name", "mode", "mode"], "ir.ui.view"
            ),
            ["name", "mode", "mode", "arch"],
        )

    def test_a_record_with_a_non_field_child_is_left_alone(self):
        """Reordering appends every field last, which moves the other child."""
        source = """
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <record id="v" model="ir.ui.view">
                    <field name="arch" type="xml"><form/></field>
                    <field name="name">n</field>
                    <value>keep me first</value>
                </record>
            </odoo>
        """
        before = textwrap.dedent(source).lstrip().encode()
        self.assertEqual(_shape(self._sort(source)), _shape(before))

    def test_field_order_is_actually_applied(self):
        out = self._sort("""
            <?xml version="1.0" encoding="utf-8"?>
            <odoo>
                <record id="v" model="ir.ui.view">
                    <field name="arch" type="xml"><form/></field>
                    <field name="name">n</field>
                </record>
            </odoo>
        """)
        names = [f.get("name") for f in etree.fromstring(out).findall("./record/field")]
        self.assertEqual(names, ["name", "arch"])


@no_retry
class TestFixersOverTheRepository(LintCase):
    """Both fixers, run over every data file they own, must not change meaning.

    This is the test that found the namespace, suffix-drop, attribute-escaping
    and duplicate-field defects. None of them is reachable from a snippet: they
    need a real EDI template, a real ``<asset>`` path, a real view. Running the
    fixer over the corpus and comparing before with after is the only exercise
    that has ever caught one, and it costs a few seconds.

    Scoped to the repository this fork owns, exactly as the gates built on
    these fixers are: reformatting a sibling checkout is not on the table, so
    neither is testing that it would survive it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data_files = [
            path
            for path in map(Path, core_xml_files())
            if _pretty_xml.is_formattable(path)
        ]

    def _run_over_the_tree(self, fixer, *, twice: bool = False):
        """Apply *fixer* to a copy of every data file, and report what it broke.

        Returns ``(offences, declined)``: an offence is a file whose structure
        or wording changed, or that stopped parsing; a decline is one the fixer
        refused, which is safe but still worth counting.
        """
        offences, declined, unsettled = [], [], []
        with tempfile.TemporaryDirectory() as tmp:
            for index, source in enumerate(self.data_files):
                original = source.read_bytes()
                try:
                    before_shape, before_words = _shape(original), _words(original)
                except etree.XMLSyntaxError:
                    continue
                target = Path(tmp) / f"{index}.xml"
                target.write_bytes(original)
                if fixer(target) is None:
                    declined.append(str(source.relative_to(core_root())))
                    continue
                once = target.read_bytes()
                try:
                    after_shape, after_words = _shape(once), _words(once)
                except etree.XMLSyntaxError as exc:
                    offences.append(f"{source}: does not parse after the pass ({exc})")
                    continue
                if before_shape != after_shape:
                    offences.append(
                        f"{source}: {len(before_shape)} element(s) before, "
                        f"{len(after_shape)} after, or an attribute changed"
                    )
                elif before_words != after_words:
                    lost = sorted(set(before_words) - set(after_words))[:5]
                    offences.append(f"{source}: text changed, e.g. lost {lost}")
                if twice and fixer(target) and target.read_bytes() != once:
                    unsettled.append(str(source))
        return offences, declined, unsettled

    def test_the_scan_reaches_the_data_files(self):
        self.assertGreater(
            len(self.data_files), 3000, "the scan reached almost nothing"
        )

    def test_the_formatter_preserves_every_data_file(self):
        """Structure and wording, over all of it, in one pass and then again.

        Four separate defects lived here and none was reachable from a snippet:
        a namespaced tag, an ``<asset>`` path long enough to wrap, a character
        reference in an attribute, a comment carrying markup. What they have in
        common is that the formatter reported success on every one.
        """
        offences, declined, unsettled = self._run_over_the_tree(
            _pretty_xml.format_xml_file, twice=True
        )
        self.assertFalse(
            offences,
            f"{len(offences)} file(s) did not survive a formatting pass:\n  "
            + "\n  ".join(offences[:40]),
        )
        self.assertFalse(
            unsettled,
            f"{len(unsettled)} file(s) change again on a second pass, so the "
            f"gate can never go green on them:\n  " + "\n  ".join(unsettled[:40]),
        )
        self.assertEqual(
            sorted(declined),
            sorted(DECLINED_BY_THE_FORMATTER),
            "the set of files the formatter refuses has moved. A new entry is a "
            "file it can no longer reproduce faithfully -- which is safe, but it "
            "is also a file the gate will never be able to report on.",
        )

    def test_the_record_sorter_preserves_every_data_file(self):
        offences, _declined, _unsettled = self._run_over_the_tree(
            _sort_xml_records.sort_xml_file
        )
        self.assertFalse(
            offences,
            f"{len(offences)} file(s) lost or gained content while being "
            f"sorted:\n  " + "\n  ".join(offences[:40]),
        )

    def test_the_two_fixers_agree_on_the_order_they_run_in(self):
        """Sorting then formatting must equal formatting the sorted file.

        They are documented as two separate commands over the same tree, so
        whichever a contributor runs first has to leave the other able to
        finish. Only the sorter changes structure, so it has to come first --
        and the formatter has to be a fixed point of the pair.
        """
        with tempfile.TemporaryDirectory() as tmp:
            disagreeing = []
            for index, source in enumerate(self.data_files[:400]):
                a = Path(tmp) / f"a{index}.xml"
                a.write_bytes(source.read_bytes())
                _sort_xml_records.sort_xml_file(a)
                if _pretty_xml.format_xml_file(a) is None:
                    continue
                after_sort_then_format = a.read_bytes()
                if _pretty_xml.format_xml_file(a):
                    if a.read_bytes() != after_sort_then_format:
                        disagreeing.append(str(source))
            self.assertFalse(
                disagreeing,
                "formatting is not stable after sorting:\n  "
                + "\n  ".join(disagreeing[:20]),
            )


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

    def test_the_cli_and_the_lint_test_select_the_same_files(self):
        """Both must ask :func:`_pretty_xml.is_formattable`, and only that.

        The check that used to stand here filtered a list by ``is_formattable``
        and then asserted that nothing in it failed ``is_formattable`` -- true
        by construction, whatever either side actually did. Comparing the two
        selections against each other is the claim that was meant.
        """
        from .test_pretty_xml import PrettyXmlLinter

        lint_selection = {str(path) for path in PrettyXmlLinter._files(self)}
        cli_selection = {
            path for path in core_xml_files() if _pretty_xml.is_formattable(Path(path))
        }
        self.assertTrue(lint_selection, "the scan reached no data files")
        self.assertEqual(
            lint_selection,
            cli_selection,
            "the gate and its remediation do not own the same files",
        )
