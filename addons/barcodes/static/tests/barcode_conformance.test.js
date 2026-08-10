/** @odoo-module native */
/**
 * JS half of the cross-runtime parser conformance suite.
 *
 * Shares its golden vectors with `barcodes/tests/test_barcode_conformance.py`
 * so the Python and JS parsers cannot drift apart again. Add a case to
 * `conformance_vectors.json`, not here.
 */

import { VECTORS as vectors } from "@barcodes/../tests/conformance_vectors";
import { BarcodeParser } from "@barcodes/js/barcode_parser";
import { expect, test } from "@odoo/hoot";

function buildParser(testCase) {
    const rules = testCase.rules.map((rule, index) => ({
        alias: "0",
        sequence: rule.sequence ?? 10 + index,
        ...rule,
    }));
    rules.sort((a, b) => a.sequence - b.sequence);
    return new BarcodeParser({
        nomenclature: { ...testCase.nomenclature, rules },
    });
}

test.tags("headless");
test("conformance: nomenclature vectors", async () => {
    for (const testCase of vectors.cases) {
        const parser = buildParser(testCase);
        for (const expectation of testCase.expected) {
            const { barcode, ...expected } = expectation;
            const result = parser.parse_barcode(barcode);
            for (const [key, value] of Object.entries(expected)) {
                expect(result[key]).toBe(value, {
                    message: `${testCase.name}: parse_barcode(${JSON.stringify(
                        barcode,
                    )})[${key}]`,
                });
            }
        }
    }
});

test.tags("headless");
test("conformance: EPC URI vectors", async () => {
    const parser = new BarcodeParser({
        nomenclature: { rules: [], upc_ean_conv: "none" },
    });
    for (const testCase of vectors.uri_cases) {
        const result = parser.parse_barcode(testCase.barcode);
        expect(Array.isArray(result)).toBe(true, {
            message: `parse_barcode(${JSON.stringify(testCase.barcode)}) must return a list`,
        });
        expect(result.length).toBe(testCase.expected.length, {
            message: JSON.stringify(testCase.barcode),
        });
        testCase.expected.forEach((expected, index) => {
            for (const [key, value] of Object.entries(expected)) {
                expect(result[index][key]).toBe(value, {
                    message: `${JSON.stringify(testCase.barcode)}[${index}].${key}`,
                });
            }
        });
    }
});
