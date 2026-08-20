import logging

from lxml import etree

from . import _sort_xml_records
from .lint_case import LintCase, core_data_files

_logger = logging.getLogger(__name__)

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)


class XmlRecordLinter(LintCase):
    @staticmethod
    def scanned_files():
        return core_data_files()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.field_order_violations = []
        cls.attrib_order_violations = []
        cls.checked = 0
        for xml_file in map(str, cls.scanned_files()):
            tree = cls._parse(xml_file)
            if tree is None:
                continue
            cls.checked += 1
            cls.field_order_violations.extend(cls._field_order(xml_file, tree))
            cls.attrib_order_violations.extend(cls._attrib_order(xml_file, tree))
        _logger.info("parsed %s XML data files once for both checks", cls.checked)

    def _assert_clean(self, violations, floor, what):
        self.assertTrue(self.checked, "the scan reached no XML files at all")
        self.assert_ratchet(
            violations,
            floor,
            what,
            "Run `_sort_xml_records.py` over this repository, then lower the floor.",
        )

    def test_xml_record_field_order(self):
        self._assert_clean(
            self.field_order_violations,
            FIELD_ORDER_FLOOR,
            "record field order violation(s)",
        )

    def test_xml_element_attrib_order(self):
        self._assert_clean(
            self.attrib_order_violations,
            ATTRIB_ORDER_FLOOR,
            "element attribute order violation(s)",
        )

    @staticmethod
    def _parse(xml_file: str) -> etree._ElementTree | None:
        try:
            return etree.parse(xml_file, _PARSER)
        except etree.XMLSyntaxError as exc:
            _logger.warning("XML parse error in %s: %s", xml_file, exc)
            return None

    @staticmethod
    def _field_order(xml_file: str, tree) -> list[str]:
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
                violations.append(
                    f"  {xml_file}: {model} id={record_id!r}: {actual} → {expected}"
                )

        return violations

    @staticmethod
    def _attrib_order(xml_file: str, tree) -> list[str]:
        violations: list[str] = []
        root = tree.getroot()

        for record in root.iter("record"):
            if record.get("model") is None:
                continue

            actual = list(record.attrib.keys())
            expected = _sort_xml_records.expected_attrib_order("record", actual)
            if actual != expected:
                rid = record.get("id") or record.get("model", "<no id>")
                violations.append(
                    f"  {xml_file}: <record> id={rid!r}: {actual} → {expected}"
                )

            for field in record:
                if callable(field.tag) or field.tag != "field":
                    continue
                actual = list(field.attrib.keys())
                expected = _sort_xml_records.expected_attrib_order("field", actual)
                if actual != expected:
                    violations.append(
                        f"  {xml_file}: <field> name={field.get('name')!r}"
                        f" in {record.get('id')!r}: {actual} → {expected}"
                    )

        for tag in _sort_xml_records._TOP_LEVEL_TAGS:
            if tag == "record":
                continue
            for elem in root.iter(tag):
                actual = list(elem.attrib.keys())
                expected = _sort_xml_records.expected_attrib_order(tag, actual)
                if actual != expected:
                    eid = elem.get("id") or elem.get("name") or elem.get("model", "?")
                    violations.append(
                        f"  {xml_file}: <{tag}> id={eid!r}: {actual} → {expected}"
                    )

        return violations


FIELD_ORDER_FLOOR = 789
ATTRIB_ORDER_FLOOR = 2455
