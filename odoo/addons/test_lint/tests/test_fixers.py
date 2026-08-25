import ast
import itertools
import tempfile
import textwrap
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest
from odoo.tests.common import BaseCase, no_retry

from . import (
    _pretty_xml,
    _sort_manifests,
    _sort_xml_records,
    _xml_identity,
    _xml_sweep,
)
from .lint_case import (
    LintCase,
    core_data_files,
    core_xml_files,
    is_core_path,
)

_PARSER = _xml_identity.PARSER

DECLINED_BY_THE_FORMATTER: list[str] = []
DECLINED_BY_THE_SORTER: list[str] = []


def _semantic(xml: bytes) -> bytes:
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
    root = etree.fromstring(xml)
    out = []

    def walk(element, depth):
        if not callable(element.tag):
            out.append((depth, element.tag, tuple(sorted(element.attrib.items()))))
        for child in element:
            walk(child, depth + 1)

    walk(root, 0)
    return sorted(out)


@no_retry
class TestPrettyXml(BaseCase):
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

    PRE_IN_ARCH = """
        <odoo>
            <record id="v" model="ir.ui.view">
                <field name="arch" type="xml">
                    <form>
                        <div>
                            <div>
                                <div>
                                    <div>
                                        <p>The value must be
                                            assigned to each record with a
                                            dictionary-like assignment.</p>
                                        <pre>
for record in self:
    record['size'] = len(record.name)
</pre>
                                        <p>The only predefined variables are</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </form>
                </field>
            </record>
        </odoo>
    """

    def test_a_pre_block_inside_an_arch_keeps_its_own_indentation(self):
        path = Path(self.tmpdir) / "arch.xml"
        path.write_bytes(textwrap.dedent(self.PRE_IN_ARCH).lstrip().encode())
        self.assertIs(_pretty_xml.format_xml_file(path), True)
        self.assertIn(
            "\nfor record in self:\n    record['size'] = len(record.name)\n",
            path.read_text(),
        )
        self.assertIs(_pretty_xml.format_xml_file(path, dry_run=True), False)

    def test_xml_space_preserve_is_honoured_on_any_tag(self):
        source = self.PRE_IN_ARCH.replace("<pre>", '<div xml:space="preserve">')
        source = source.replace("</pre>", "</div>")
        path = Path(self.tmpdir) / "space.xml"
        path.write_bytes(textwrap.dedent(source).lstrip().encode())
        self.assertIs(_pretty_xml.format_xml_file(path), True)
        self.assertIn(
            "\nfor record in self:\n    record['size'] = len(record.name)\n",
            path.read_text(),
        )

    def test_the_faithfulness_check_sees_a_reindented_preserve_block(self):
        original = b"<odoo><t><pre>\nfor x in y:\n    z(x)\n</pre></t></odoo>"
        flattened = b"<odoo><t><pre>\nfor x in y:\nz(x)\n</pre></t></odoo>"
        self.assertFalse(_xml_identity.is_faithful(original, flattened))
        prose = b"<odoo><t><p>one\n   two</p></t></odoo>"
        rewrapped = b"<odoo><t><p>one\n      two</p></t></odoo>"
        self.assertTrue(_xml_identity.is_faithful(prose, rewrapped))

    def test_text_between_children_survives(self):
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

    def test_the_self_check_covers_the_prologue_too(self):
        document = (
            b'<?xml version="1.0" encoding="utf-8"?>\n'
            b'<!DOCTYPE odoo SYSTEM "odoo.dtd">\n'
            b"<!-- Copyright 2026 AgroMarin -->\n"
            b"<odoo>\n"
            b'    <record id="r" model="m"><field name="a">1</field></record>\n'
            b"</odoo>\n"
        )
        path = Path(self.tmpdir) / "prologue.xml"
        path.write_bytes(document)
        _pretty_xml.format_xml_file(path)
        rebuilt = path.read_text()

        self.assertTrue(
            _xml_identity.is_faithful(document, rebuilt.encode()),
            "the formatter's own output must read as faithful",
        )
        for label, prefix in (
            ("the doctype", "<!DOCTYPE"),
            ("the pre-root comment", "<!--"),
            ("the xml declaration", "<?xml "),
        ):
            with self.subTest(loses=label):
                lines = [
                    line for line in rebuilt.split("\n") if not line.startswith(prefix)
                ]
                mutated = "\n".join(lines).encode()
                self.assertNotEqual(mutated, rebuilt.encode(), f"{label} not dropped")
                self.assertFalse(
                    _xml_identity.is_faithful(document, mutated),
                    f"losing {label} must not read as a faithful rewrite",
                )


@no_retry
class TestSortXmlRecords(BaseCase):
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
        self.assertEqual(
            _sort_xml_records.expected_field_order(
                ["arch", "name", "mode", "mode"], "ir.ui.view"
            ),
            ["name", "mode", "mode", "arch"],
        )

    def test_a_record_with_a_non_field_child_is_left_alone(self):
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
    """Both fixers, over every core data file, in one pass each.

    What this used to assert with `_shape` and `_words` -- sorted projections of
    the element tree and its text -- is now `_xml_identity.comparable`, which
    both fixers already refuse to write against. The projections were strictly
    weaker in every direction but one (attribute-value whitespace), and that one
    is folded into the shared definition, so re-deriving them here bought
    nothing: `format_xml_file` cannot return True for output the check rejects.
    Proven by mutation -- a formatter made to swallow comments was caught 143
    times by the identity check and 0 times by `_shape`/`_words`.
    """

    def test_the_scan_reaches_the_data_files(self):
        self.assertGreater(
            _xml_sweep.formatter_sweep().checked,
            3000,
            "the scan reached almost nothing",
        )

    def test_the_formatter_settles_on_every_data_file(self):
        sweep = _xml_sweep.formatter_sweep()
        self.assertFalse(
            sweep.unsettled,
            f"{len(sweep.unsettled)} file(s) change again on a second pass, so "
            f"the gate can never go green on them:\n  "
            + "\n  ".join(sweep.unsettled[:40]),
        )
        self.assertEqual(
            sorted(sweep.declined),
            sorted(DECLINED_BY_THE_FORMATTER),
            "the set of files the formatter refuses has moved. A new entry is a "
            "file it can no longer reproduce faithfully -- which is safe, but it "
            "is also a file the gate will never be able to report on.",
        )

    def test_the_record_sorter_settles_on_every_data_file(self):
        sweep = _xml_sweep.sorter_sweep()
        self.assertEqual(
            sorted(sweep.declined),
            sorted(DECLINED_BY_THE_SORTER),
            "the sorter refused a file. Until this change it had no faithfulness "
            "check at all and wrote whatever lxml serialised -- though it is the "
            "fixer that MOVES elements -- so a refusal here is new information, "
            "not a regression.",
        )
        self.assertFalse(
            sweep.unsettled,
            f"{len(sweep.unsettled)} file(s) sort differently on a second pass:\n  "
            + "\n  ".join(sweep.unsettled[:40]),
        )

    def test_the_two_fixers_agree_on_the_order_they_run_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            disagreeing = []
            for index, source in enumerate(core_data_files()[:400]):
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
class TestSortManifests(BaseCase):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, source: str) -> Path:
        path = Path(self.tmpdir) / "__manifest__.py"
        path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        return path

    def _roundtrip(self, value: object) -> None:
        path = self._write(f'{{\n    "name": "m",\n    "description": {value!r},\n}}\n')
        before = ast.literal_eval(_manifest_dict(path))
        result = _sort_manifests.sort_manifest(path)
        self.assertIsNotNone(result, "the fixer declined a manifest it should render")
        self.assertEqual(ast.literal_eval(_manifest_dict(path)), before)

    def test_a_multiline_string_ending_in_a_quote_does_not_break_the_file(self):
        for value in (
            'Multi-line description\nthat ends in a quoted "word"',
            "Multi-line\nending in a backslash \\",
            'Has an embedded """ triple quote\nand more',
        ):
            with self.subTest(value=value):
                rendered = _sort_manifests._fmt_str(value)
                self.assertEqual(
                    ast.literal_eval(rendered),
                    value,
                    f"{rendered!r} does not round-trip",
                )

    def test_every_string_shape_round_trips(self):
        pieces = [
            "",
            "a",
            '"',
            '""',
            '"""',
            "\\",
            "\\\\",
            "\n",
            "\n\n",
            "'",
            "\t",
            "\r",
            "\x00",
            " ",
            'end"',
            '"start',
        ]
        values = {
            "".join(combo)
            for length in (1, 2, 3)
            for combo in itertools.product(pieces, repeat=length)
        }
        broken = []
        for value in sorted(values):
            rendered = _sort_manifests._fmt_str(value)
            try:
                if ast.literal_eval(rendered) != value:
                    broken.append((value, rendered))
            except SyntaxError, ValueError:
                broken.append((value, rendered))
        self.assertFalse(
            broken,
            f"{len(broken)} of {len(values)} string shapes do not round-trip, "
            f"e.g. {broken[:3]}",
        )

    def test_values_survive_the_rewrite(self):
        for value in (
            "plain",
            "two\nlines",
            'ends in a quote"',
            'multi\nline ending in a quote"',
            "unicode — em dash, ünïcode",
            "",
        ):
            with self.subTest(value=value):
                self._roundtrip(value)

    def test_keys_are_reordered_and_nothing_is_lost(self):
        path = self._write("""
            {
                "depends": ["base"],
                "name": "thing",
                "license": "LGPL-3",
                "version": "0.1",
            }
        """)
        before = ast.literal_eval(_manifest_dict(path))
        self.assertIs(_sort_manifests.sort_manifest(path), True)
        after = ast.literal_eval(_manifest_dict(path))
        self.assertEqual(after, before, "reordering must not change the value")
        self.assertEqual(
            list(after), ["name", "version", "license", "depends"], "and must reorder"
        )

    def test_a_header_comment_is_kept(self):
        path = self._write("""
            # -*- coding: utf-8 -*-
            # Part of Odoo. See LICENSE file for full copyright and licensing details.
            {
                "depends": ["base"],
                "name": "thing",
            }
        """)
        _sort_manifests.sort_manifest(path)
        self.assertIn("Part of Odoo", path.read_text())

    def test_sorting_is_idempotent(self):
        path = self._write("""
            {
                "depends": ["base"],
                "name": "thing",
                "description": "a\\nb",
            }
        """)
        self.assertIs(_sort_manifests.sort_manifest(path), True)
        once = path.read_text()
        self.assertIs(_sort_manifests.sort_manifest(path), False)
        self.assertEqual(path.read_text(), once)

    def test_an_unfaithful_rewrite_is_refused_rather_than_written(self):
        path = self._write("""
            {
                "depends": ["base"],
                "name": "thing",
            }
        """)
        original = path.read_bytes()
        real = _sort_manifests._fmt_value
        try:
            _sort_manifests._fmt_value = lambda value, depth: '"clobbered"'
            self.assertIsNone(_sort_manifests.sort_manifest(path))
        finally:
            _sort_manifests._fmt_value = real
        self.assertEqual(path.read_bytes(), original, "the file must be untouched")


def _manifest_dict(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
            return ast.unparse(node.value)
    raise AssertionError(f"no dict literal left in {path}")


@no_retry
class TestSortManifestsOverTheRepository(LintCase):
    def test_every_manifest_round_trips(self):
        offences = []
        checked = 0
        with tempfile.TemporaryDirectory() as tmp:
            for index, manifest in enumerate(Manifest.all_addon_manifests()):
                source = Path(manifest.path) / "__manifest__.py"
                if not is_core_path(str(source)) or not source.is_file():
                    continue
                try:
                    before = ast.literal_eval(_manifest_dict(source))
                except SyntaxError, ValueError, AssertionError:
                    continue
                checked += 1
                target = Path(tmp) / f"{index}__manifest__.py"
                target.write_bytes(source.read_bytes())
                if _sort_manifests.sort_manifest(target) is None:
                    offences.append(f"{manifest.name}: declined by the fixer")
                    continue
                try:
                    after = ast.literal_eval(_manifest_dict(target))
                except (SyntaxError, ValueError, AssertionError) as exc:
                    offences.append(f"{manifest.name}: does not parse after: {exc}")
                    continue
                if after != before:
                    offences.append(f"{manifest.name}: value changed")

        self.assertGreater(checked, 100, "the scan reached almost no manifests")
        self.assertFalse(
            offences,
            f"{len(offences)} manifest(s) did not survive the sorter:\n  "
            + "\n  ".join(offences[:40]),
        )


@no_retry
class TestFixerScope(LintCase):
    def test_static_templates_are_not_data_files(self):
        self.assertFalse(
            _pretty_xml.is_formattable(Path("/a/account/static/src/x.xml"))
        )
        self.assertTrue(_pretty_xml.is_formattable(Path("/a/account/views/x.xml")))

    def test_the_cli_and_the_lint_test_select_the_same_files(self):
        lint_selection = {str(path) for path in core_data_files()}
        cli_selection = {
            path for path in core_xml_files() if _pretty_xml.is_formattable(Path(path))
        }
        self.assertTrue(lint_selection, "the scan reached no data files")
        self.assertEqual(
            lint_selection,
            cli_selection,
            "the gate and its remediation do not own the same files",
        )

    def test_both_xml_gates_own_the_same_files_as_both_fixers(self):
        from .test_xml_records import XmlRecordLinter

        shared = {str(path) for path in core_data_files()}
        self.assertTrue(shared, "the shared selection reached no data files")
        self.assertEqual({str(p) for p in XmlRecordLinter.scanned_files()}, shared)
        self.assertEqual(
            _xml_sweep.formatter_sweep().checked
            + len(_xml_sweep.formatter_sweep().unparseable),
            len(shared),
            "the formatter sweep and the shared selection disagree",
        )

    def test_no_fixture_directory_is_selected_as_data(self):
        """A fixture is not a data file, and canonicalising one is a defect.

        271 of the 3641 units this gate's floor used to carry lived under a
        tests/ directory, including l10n_it_edi's deliberately malformed EDI
        samples -- one of which does not parse at all. No manifest names a data
        or demo file under tests/, so nothing that loads is lost.
        """
        self.assertFalse(
            [str(path) for path in core_data_files() if "tests" in path.parts],
            "a tests/ fixture is being held to the data-file conventions",
        )

    def test_the_cli_walk_selects_what_the_gate_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            laid_out = [
                "views/a.xml",
                "data/b.xml",
                "static/src/xml/c.xml",
                "_vendor/d.xml",
                "node_modules/e.xml",
                "enterprise_like/f.xml",
            ]
            for relative in laid_out:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"<odoo/>\n")

            walked = {
                str(path.relative_to(root))
                for path in _pretty_xml.iter_target_files([root])
            }
            self.assertEqual(
                walked,
                {"views/a.xml", "data/b.xml", "enterprise_like/f.xml"},
                "the CLI walk and is_formattable disagree",
            )
            self.assertTrue(
                all(_pretty_xml.is_formattable(root / relative) for relative in walked),
                "the CLI walked a file the gate would never report",
            )

    def test_neither_fixer_names_a_sibling_checkout_by_directory(self):
        for module in (_pretty_xml, _sort_xml_records, _sort_manifests):
            with self.subTest(fixer=module.__name__):
                defaults = [
                    action.default
                    for action in module.build_parser()._actions
                    if action.dest == "exclude"
                ]
                self.assertTrue(defaults, "no --exclude option to inspect")
                self.assertNotIn(
                    "enterprise",
                    defaults[0],
                    "scope by is_core_path, not by a hard-coded sibling name",
                )
