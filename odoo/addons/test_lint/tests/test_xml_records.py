import logging

from lxml import etree

from . import _sort_xml_records
from .lint_case import LintCase

_logger = logging.getLogger(__name__)

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)


class XmlRecordLinter(LintCase):
    def test_xml_record_field_order(self):
        for xml_file in self.iter_module_files("*.xml"):
            with self.subTest(file=xml_file):
                self._check_field_order(xml_file)

    def test_xml_element_attrib_order(self):
        for xml_file in self.iter_module_files("*.xml"):
            with self.subTest(file=xml_file):
                self._check_attrib_order(xml_file)

    def _parse(self, xml_file: str) -> etree._ElementTree | None:
        try:
            return etree.parse(xml_file, _PARSER)
        except etree.XMLSyntaxError as exc:
            _logger.warning("XML parse error in %s: %s", xml_file, exc)
            return None

    def _check_field_order(self, xml_file: str) -> None:
        tree = self._parse(xml_file)
        if tree is None:
            return

        violations: list[str] = []
        for record in tree.getroot().iter("record"):
            model = record.get("model")
            if model not in _sort_xml_records.FIELD_ORDER:
                continue
            if any(callable(c.tag) for c in record):
                continue

            fields = [c for c in record if not callable(c.tag) and c.tag == "field"]
            actual = [f.get("name") for f in fields]
            expected = _sort_xml_records.expected_field_order(actual, model)

            if actual != expected:
                record_id = record.get("id", "<no id>")
                violations.append(f"  {model} id={record_id!r}: {actual} → {expected}")

        if violations:
            self.fail(
                f"XML record field order violations in {xml_file}:\n"
                + "\n".join(violations)
            )

    def _check_attrib_order(self, xml_file: str) -> None:
        tree = self._parse(xml_file)
        if tree is None:
            return

        violations: list[str] = []
        root = tree.getroot()

        for record in root.iter("record"):
            if record.get("model") is None:
                continue

            actual = list(record.attrib.keys())
            expected = _sort_xml_records.expected_attrib_order("record", actual)
            if actual != expected:
                rid = record.get("id") or record.get("model", "<no id>")
                violations.append(f"  <record> id={rid!r}: {actual} → {expected}")

            for field in record:
                if callable(field.tag) or field.tag != "field":
                    continue
                actual = list(field.attrib.keys())
                expected = _sort_xml_records.expected_attrib_order("field", actual)
                if actual != expected:
                    violations.append(
                        f"  <field> name={field.get('name')!r}"
                        f" in {record.get('id')!r}: {actual} → {expected}"
                    )

        for tag in _sort_xml_records._TOP_LEVEL_TAGS:
            for elem in root.iter(tag):
                actual = list(elem.attrib.keys())
                expected = _sort_xml_records.expected_attrib_order(tag, actual)
                if actual != expected:
                    eid = elem.get("id") or elem.get("name") or elem.get("model", "?")
                    violations.append(f"  <{tag}> id={eid!r}: {actual} → {expected}")

        if violations:
            self.fail(
                f"XML element attribute order violations in {xml_file}:\n"
                + "\n".join(violations)
            )
