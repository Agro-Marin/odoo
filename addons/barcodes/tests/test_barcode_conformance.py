"""Python half of the cross-runtime parser conformance suite.

The barcode parser exists twice, in Python and in JS, and the two drifted apart
silently for years. Both halves now read the same golden vectors, so a change
that moves one runtime and not the other fails on the side that did not move.

The JS half is ``barcodes/static/tests/barcode_conformance.test.js``; the
vectors are ``barcodes/static/tests/conformance_vectors.js``.
"""

import json
from pathlib import Path

from odoo.tests import common
from odoo.tools.misc import file_path

VECTORS_PATH = "barcodes/static/tests/conformance_vectors.js"


def load_vectors():
    """Parse the golden vectors out of the ES module both runtimes share.

    The file is a JS module so the HOOT suite can import it, and its payload is
    a JSON string in a template literal so this side needs no JS engine -- and,
    unlike an object literal, prettier leaves it alone instead of unquoting the
    keys into something ``json.loads`` rejects.
    """
    source = Path(file_path(VECTORS_PATH)).read_text(encoding="utf-8")
    start = source.index("`") + 1
    return json.loads(source[start : source.index("`", start)])


class TestBarcodeConformance(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vectors = load_vectors()

    def _build_nomenclature(self, case):
        nomenclature = self.env["barcode.nomenclature"].create(
            {"name": case["name"], **case["nomenclature"]}
        )
        for index, rule in enumerate(case["rules"]):
            self.env["barcode.rule"].create(
                {
                    "name": f"{case['name']} #{index}",
                    "barcode_nomenclature_id": nomenclature.id,
                    "sequence": rule.get("sequence", 10 + index),
                    **{k: v for k, v in rule.items() if k != "sequence"},
                }
            )
        nomenclature.invalidate_recordset(["rule_ids"])
        return nomenclature

    def test_conformance_vectors(self):
        """Every nomenclature vector parses to the documented result."""
        for case in self.vectors["cases"]:
            nomenclature = self._build_nomenclature(case)
            for expectation in case["expected"]:
                barcode = expectation["barcode"]
                with self.subTest(case=case["name"], barcode=barcode):
                    result = nomenclature.parse_barcode(barcode)
                    for key, expected in expectation.items():
                        if key == "barcode":
                            continue
                        self.assertEqual(
                            result[key],
                            expected,
                            f"{case['name']}: parse_barcode({barcode!r})[{key!r}]",
                        )

    def test_conformance_uri_vectors(self):
        """Every EPC URI vector decodes to the documented list of parts."""
        nomenclature = self.env["barcode.nomenclature"].create({"name": "uri"})
        for case in self.vectors["uri_cases"]:
            barcode = case["barcode"]
            with self.subTest(barcode=barcode):
                result = nomenclature.parse_barcode(barcode)
                self.assertIsInstance(
                    result, list, f"parse_barcode({barcode!r}) must return a list"
                )
                self.assertEqual(len(result), len(case["expected"]), barcode)
                for part, expected in zip(result, case["expected"], strict=True):
                    for key, value in expected.items():
                        self.assertEqual(part[key], value, f"{barcode!r}[{key!r}]")
