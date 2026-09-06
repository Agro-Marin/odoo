import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    defineWebModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

import "@extract/extraction/extraction_field";

const READ = {
    total: {
        value: 1234.56,
        source: "invoice_template",
        confidence: 0.92,
        disputed: false,
        candidates: [
            { value: 1234.56, source: "invoice_template", confidence: 0.92 },
            { value: 1234.0, source: "ocr", confidence: 0.4 },
        ],
    },
    vendor_name: {
        value: "ACME",
        source: "ocr",
        confidence: 0.5,
        disputed: true,
        candidates: [],
    },
};

class ReadDoc extends models.Model {
    _name = "read.doc";
    extract_state = fields.Selection({
        selection: [
            ["none", "Not extracted"],
            ["partial", "Partially extracted"],
            ["done", "Extracted"],
        ],
    });
    extract_result = fields.Json();
    extract_missing = fields.Json();
    extract_corrections = fields.Json();
    extract_error = fields.Text();
    _records = [
        {
            id: 1,
            extract_state: "partial",
            extract_result: READ,
            extract_missing: { fields: ["invoice_date"], rules: ["invoice_totals"] },
            extract_corrections: {
                vendor_name: {
                    read: "ACME",
                    read_by: "ocr",
                    corrected_to: "ACME Corp",
                },
            },
            extract_error: false,
        },
        {
            id: 2,
            extract_state: "none",
            extract_result: false,
            extract_missing: false,
            extract_corrections: false,
            extract_error: false,
        },
    ];
}

defineWebModels();
defineModels([ReadDoc]);

const ARCH = `<form><field name="extract_result" widget="document_extraction"/></form>`;

test("what was read is a table, not a JSON dump", async () => {
    await mountView({ type: "form", resModel: "read.doc", resId: 1, arch: ARCH });
    const rows = document.querySelectorAll(".o_document_extraction_read tbody tr");
    const text = document.querySelector(".o_document_extraction").textContent;
    expect(rows.length).toBe(3, {
        message: "two read fields plus the one candidate that lost",
    });
    expect(text).toInclude("1234.56");
    expect(text).toInclude("invoice_template");
    expect(text).toInclude("92");
    expect(text).not.toInclude('{"value"');
});

test("a disputed reading is marked", async () => {
    await mountView({ type: "form", resModel: "read.doc", resId: 1, arch: ARCH });
    const disputed = document.querySelectorAll(
        ".o_document_extraction_read tbody tr.table-warning",
    );
    expect(disputed.length).toBe(1);
    expect(disputed[0].textContent).toInclude("vendor_name");
});

test("what nobody could read, and what does not add up, are both shown", async () => {
    await mountView({ type: "form", resModel: "read.doc", resId: 1, arch: ARCH });
    const alert = document.querySelector(".o_document_extraction .alert");
    expect(alert.textContent).toInclude("invoice_date");
    expect(alert.textContent).toInclude("invoice_totals");
});

test("a correction shows what was read and what it became", async () => {
    await mountView({ type: "form", resModel: "read.doc", resId: 1, arch: ARCH });
    const row = document.querySelector(".o_document_extraction_corrections tbody tr");
    expect(row.textContent).toInclude("ACME Corp");
    expect(row.textContent).toInclude("ocr");
});

test("an unread document says so instead of rendering an empty table", async () => {
    await mountView({ type: "form", resModel: "read.doc", resId: 2, arch: ARCH });
    expect(document.querySelectorAll(".o_document_extraction_read").length).toBe(0);
    expect(document.querySelector(".o_document_extraction").textContent).toInclude(
        "has not been read",
    );
});
