// @ts-check

/**
 * Pure unit tests for record_value_transforms.js.
 *
 * Tests formatServerValue, getDefaultValues, getTextValues, and
 * computeDataContext without OWL, DOM, or a mock server.
 *
 * Date/datetime paths use luxon.DateTime (globally available in Hoot).
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    computeDataContext,
    formatServerValue,
    getDefaultValues,
    getTextValues,
} from "@web/model/relational_model/record_value_transforms";

const { DateTime } = luxon;

// ---------------------------------------------------------------------------
// formatServerValue
// ---------------------------------------------------------------------------

describe("formatServerValue — char / text", () => {
    test("passes through a non-empty char value", () => {
        expect(formatServerValue("char", "hello")).toBe("hello");
    });

    test("converts empty char to false", () => {
        expect(formatServerValue("char", "")).toBe(false);
    });

    test("passes through non-empty text value", () => {
        expect(formatServerValue("text", "some text")).toBe("some text");
    });

    test("converts empty text to false", () => {
        expect(formatServerValue("text", "")).toBe(false);
    });
});

describe("formatServerValue — html", () => {
    test("passes through non-empty html", () => {
        expect(formatServerValue("html", "<p>body</p>")).toBe("<p>body</p>");
    });

    test("converts empty html to false", () => {
        expect(formatServerValue("html", "")).toBe(false);
    });

    test("converts null html to false", () => {
        expect(formatServerValue("html", null)).toBe(false);
    });
});

describe("formatServerValue — many2one", () => {
    test("returns id when many2one has a value", () => {
        expect(formatServerValue("many2one", { id: 5, display_name: "Test" })).toBe(5);
    });

    test("returns false for falsy many2one", () => {
        expect(formatServerValue("many2one", false)).toBe(false);
        expect(formatServerValue("many2one", null)).toBe(false);
    });
});

describe("formatServerValue — many2one_reference", () => {
    test("returns resId when many2one_reference has a value", () => {
        expect(formatServerValue("many2one_reference", { resId: 10, resModel: "res.partner" })).toBe(10);
    });

    test("returns 0 for falsy many2one_reference", () => {
        expect(formatServerValue("many2one_reference", false)).toBe(0);
        expect(formatServerValue("many2one_reference", null)).toBe(0);
    });
});

describe("formatServerValue — reference", () => {
    test("returns 'model,id' string when fully populated", () => {
        expect(formatServerValue("reference", { resModel: "res.partner", resId: 3 })).toBe("res.partner,3");
    });

    test("returns false when resModel is absent", () => {
        expect(formatServerValue("reference", { resModel: "", resId: 3 })).toBe(false);
    });

    test("returns false when resId is absent", () => {
        expect(formatServerValue("reference", { resModel: "res.partner", resId: 0 })).toBe(false);
    });

    test("returns false for falsy reference", () => {
        expect(formatServerValue("reference", false)).toBe(false);
    });
});

describe("formatServerValue — date / datetime", () => {
    test("returns false for falsy date", () => {
        expect(formatServerValue("date", false)).toBe(false);
    });

    test("returns false for falsy datetime", () => {
        expect(formatServerValue("datetime", false)).toBe(false);
    });

    test("serializes a valid date to server string", () => {
        const dt = DateTime.fromObject({ year: 2024, month: 6, day: 15 });
        const result = formatServerValue("date", dt);
        expect(typeof result).toBe("string");
        expect(result).toBe("2024-06-15");
    });

    test("serializes a valid datetime to server string", () => {
        const dt = DateTime.fromObject(
            { year: 2024, month: 6, day: 15, hour: 10, minute: 30, second: 0 },
            { zone: "UTC" },
        );
        const result = formatServerValue("datetime", dt);
        expect(typeof result).toBe("string");
        expect(result).toBe("2024-06-15 10:30:00");
    });
});

describe("formatServerValue — properties", () => {
    test("formats many2one property value as [id, display_name]", () => {
        const input = [
            {
                type: "many2one",
                name: "partner",
                value: { id: 7, display_name: "Alice" },
            },
        ];
        const result = formatServerValue("properties", input);
        expect(result[0].value).toEqual([7, "Alice"]);
    });

    test("converts falsy many2one property value to null", () => {
        const input = [{ type: "many2one", name: "partner", value: null }];
        const result = formatServerValue("properties", input);
        // null && [...] evaluates to null
        expect(result[0].value).toBe(null);
    });

    test("passes through non-relational property values via recursive call", () => {
        const input = [{ type: "char", name: "notes", value: "hello" }];
        const result = formatServerValue("properties", input);
        expect(result[0].value).toBe("hello");
    });

    test("converts empty char property value to false", () => {
        const input = [{ type: "char", name: "notes", value: "" }];
        const result = formatServerValue("properties", input);
        expect(result[0].value).toBe(false);
    });

    test("does not mutate the original property objects", () => {
        const prop = { type: "char", name: "notes", value: "test" };
        const input = [prop];
        formatServerValue("properties", input);
        expect(prop.value).toBe("test"); // original untouched
    });
});

describe("formatServerValue — default passthrough", () => {
    test("passes through integer value unchanged", () => {
        expect(formatServerValue("integer", 42)).toBe(42);
    });

    test("passes through float value unchanged", () => {
        expect(formatServerValue("float", 3.14)).toBe(3.14);
    });

    test("passes through false unchanged for unknown type", () => {
        expect(formatServerValue("selection", false)).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// getDefaultValues
// ---------------------------------------------------------------------------

describe("getDefaultValues", () => {
    const fields = {
        id: { type: "integer" },
        qty: { type: "integer" },
        price: { type: "float" },
        balance: { type: "monetary" },
        name: { type: "char" },
        active: { type: "boolean" },
        line_ids: { type: "one2many" },
        tag_ids: { type: "many2many" },
    };

    test("id field returns false (not 0)", () => {
        const result = getDefaultValues(["id"], fields);
        expect(result.id).toBe(false);
    });

    test("non-id integer field returns 0", () => {
        const result = getDefaultValues(["qty"], fields);
        expect(result.qty).toBe(0);
    });

    test("float field returns 0", () => {
        const result = getDefaultValues(["price"], fields);
        expect(result.price).toBe(0);
    });

    test("monetary field returns 0", () => {
        const result = getDefaultValues(["balance"], fields);
        expect(result.balance).toBe(0);
    });

    test("one2many field returns empty array", () => {
        const result = getDefaultValues(["line_ids"], fields);
        expect(result.line_ids).toEqual([]);
    });

    test("many2many field returns empty array", () => {
        const result = getDefaultValues(["tag_ids"], fields);
        expect(result.tag_ids).toEqual([]);
    });

    test("char and other types return false", () => {
        const result = getDefaultValues(["name", "active"], fields);
        expect(result.name).toBe(false);
        expect(result.active).toBe(false);
    });

    test("handles multiple fields in one call", () => {
        const result = getDefaultValues(["id", "qty", "line_ids", "name"], fields);
        expect(result).toEqual({ id: false, qty: 0, line_ids: [], name: false });
    });
});

// ---------------------------------------------------------------------------
// getTextValues
// ---------------------------------------------------------------------------

describe("getTextValues", () => {
    const fields = {
        name: { type: "char" },
        notes: { type: "text" },
        body: { type: "html" },
        amount: { type: "float" },
        partner_id: { type: "many2one" },
    };

    test("extracts char, text, and html field values", () => {
        const activeFields = { name: {}, notes: {}, body: {} };
        const values = { name: "Alice", notes: "some text", body: "<p>html</p>" };
        const result = getTextValues(values, activeFields, fields);
        expect(result).toEqual({ name: "Alice", notes: "some text", body: "<p>html</p>" });
    });

    test("excludes non-text field types", () => {
        const activeFields = { amount: {}, partner_id: {} };
        const values = { amount: 42, partner_id: { id: 1 } };
        const result = getTextValues(values, activeFields, fields);
        expect(Object.keys(result).length).toBe(0);
    });

    test("excludes fields not in activeFields", () => {
        const activeFields = { name: {} }; // notes not active
        const values = { name: "Alice", notes: "note" };
        const result = getTextValues(values, activeFields, fields);
        expect("notes" in result).toBe(false);
        expect(result.name).toBe("Alice");
    });

    test("preserves false and empty string values for text fields", () => {
        const activeFields = { name: {}, notes: {} };
        const values = { name: false, notes: "" };
        const result = getTextValues(values, activeFields, fields);
        expect(result.name).toBe(false);
        expect(result.notes).toBe("");
    });
});

// ---------------------------------------------------------------------------
// computeDataContext
// ---------------------------------------------------------------------------

describe("computeDataContext", () => {
    const fields = {
        name: { type: "char" },
        amount: { type: "float" },
        partner_id: { type: "many2one" },
        category: { type: "reference" },
        line_ids: { type: "one2many" },
        tag_ids: { type: "many2many" },
        notes: { type: "text" },
        props: { type: "properties" },
        derived: { type: "char", relatedPropertyField: true },
    };

    test("always sets id from resId", () => {
        const { withVirtualIds } = computeDataContext({}, fields, {}, 42);
        expect(withVirtualIds.id).toBe(42);
    });

    test("sets id to false when resId is 0", () => {
        const { withVirtualIds } = computeDataContext({}, fields, {}, 0);
        expect(withVirtualIds.id).toBe(false);
    });

    test("char/text/html fields use textValues, not data values", () => {
        const data = { name: "data_name", notes: "data_notes" };
        const textValues = { name: "text_name", notes: "text_notes" };
        const { withVirtualIds } = computeDataContext(data, fields, textValues, 1);
        expect(withVirtualIds.name).toBe("text_name");
        expect(withVirtualIds.notes).toBe("text_notes");
    });

    test("many2one field uses value.id", () => {
        const data = { partner_id: { id: 7, display_name: "Alice" } };
        const { withVirtualIds } = computeDataContext(data, fields, {}, 1);
        expect(withVirtualIds.partner_id).toBe(7);
    });

    test("falsy many2one is passed as-is", () => {
        const data = { partner_id: false };
        const { withVirtualIds } = computeDataContext(data, fields, {}, 1);
        // false is falsy so passes through default branch
        expect(withVirtualIds.partner_id).toBe(false);
    });

    test("reference field uses 'model,id' format", () => {
        const data = { category: { resModel: "product.category", resId: 3 } };
        const { withVirtualIds } = computeDataContext(data, fields, {}, 1);
        expect(withVirtualIds.category).toBe("product.category,3");
    });

    test("x2many withVirtualIds includes virtual IDs", () => {
        const data = { line_ids: { currentIds: [1, "virtual_1", 2] } };
        const { withVirtualIds, withoutVirtualIds } = computeDataContext(data, fields, {}, 1);
        expect(withVirtualIds.line_ids).toEqual([1, "virtual_1", 2]);
        expect(withoutVirtualIds.line_ids).toEqual([1, 2]);
    });

    test("x2many withoutVirtualIds filters out string IDs", () => {
        const data = { tag_ids: { currentIds: ["virtual_2", 5] } };
        const { withoutVirtualIds } = computeDataContext(data, fields, {}, 1);
        expect(withoutVirtualIds.tag_ids).toEqual([5]);
    });

    test("skips relatedPropertyField entries", () => {
        const data = { derived: "value" };
        const { withVirtualIds } = computeDataContext(data, fields, {}, 1);
        expect("derived" in withVirtualIds).toBe(false);
    });

    test("properties field is filtered to non-deleted entries", () => {
        const data = {
            props: [
                { name: "p1", definition_deleted: true },
                { name: "p2" },
            ],
        };
        const { withVirtualIds } = computeDataContext(data, fields, {}, 1);
        expect(withVirtualIds.props).toEqual([{ name: "p2" }]);
    });

    test("float passes through default branch", () => {
        const data = { amount: 99.5 };
        const { withVirtualIds } = computeDataContext(data, fields, {}, 1);
        expect(withVirtualIds.amount).toBe(99.5);
    });

    test("date field serializes to server string", () => {
        const dt = DateTime.fromObject({ year: 2024, month: 3, day: 20 });
        const dateFields = { dob: { type: "date" } };
        const data = { dob: dt };
        const { withVirtualIds } = computeDataContext(data, dateFields, {}, 1);
        expect(withVirtualIds.dob).toBe("2024-03-20");
    });

    test("datetime field serializes to server string", () => {
        const dt = DateTime.fromObject(
            { year: 2024, month: 3, day: 20, hour: 8, minute: 0, second: 0 },
            { zone: "UTC" },
        );
        const datetimeFields = { created_at: { type: "datetime" } };
        const data = { created_at: dt };
        const { withVirtualIds } = computeDataContext(data, datetimeFields, {}, 1);
        expect(withVirtualIds.created_at).toBe("2024-03-20 08:00:00");
    });
});
