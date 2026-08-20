// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    buildInlinePlaceholder,
    buildQwebPlaceholder,
    escapeInlineDefault,
    isRenderableFieldType,
    placeholderExpression,
} from "@web/fields/dynamic_placeholder_syntax";

describe("placeholderExpression", () => {
    test("a plain field is the bare path", () => {
        expect(placeholderExpression("partner_id.name")).toBe("object.partner_id.name");
    });

    test("a datetime is localised, with the recipient's timezone when there is one", () => {
        expect(placeholderExpression("date_end", { fieldType: "datetime" })).toBe(
            "format_datetime(object.date_end)",
        );
        expect(
            placeholderExpression("date_end", {
                fieldType: "datetime",
                tzPath: "partner_id",
            }),
        ).toBe("format_datetime(object.date_end, tz=object.partner_id.tz)");
    });

    test("a date is formatted too -- neither producer used to", () => {
        expect(placeholderExpression("date_start", { fieldType: "date" })).toBe(
            "format_date(object.date_start)",
        );
    });

    test("both producers agree on the same field", () => {
        const spec = { path: "date_end", fieldType: "datetime", tzPath: "partner_id" };
        expect(buildQwebPlaceholder(spec).expression).toBe(
            buildInlinePlaceholder(spec).slice(2, -2),
        );
    });
});

describe("escapeInlineDefault", () => {
    test("`}}` in a default no longer terminates the placeholder", () => {
        expect(buildInlinePlaceholder({ path: "x", defaultValue: "see }} here" })).toBe(
            "{{object.x ||| see \\}\\} here}}",
        );
    });

    test("a backslash is escaped so it cannot escape the terminator", () => {
        expect(escapeInlineDefault("a\\b")).toBe("a\\\\b");
        expect(buildInlinePlaceholder({ path: "x", defaultValue: "trail\\" })).toBe(
            "{{object.x ||| trail\\\\}}",
        );
    });

    test("`|||` in a default is left exactly as typed", () => {
        // The old hook stripped the first occurrence and only the first, which
        // guarded against nothing: the grammar always splits on the separator
        // the builder itself writes.
        expect(
            buildInlinePlaceholder({ path: "x", defaultValue: "a ||| b ||| c" }),
        ).toBe("{{object.x ||| a ||| b ||| c}}");
    });

    test("no default means no separator", () => {
        expect(buildInlinePlaceholder({ path: "x" })).toBe("{{object.x}}");
        expect(buildInlinePlaceholder({ path: "x", defaultValue: "" })).toBe(
            "{{object.x}}",
        );
    });
});

describe("isRenderableFieldType", () => {
    test("binary is refused -- it renders as the repr of the bytes", () => {
        expect(isRenderableFieldType({ type: "binary" })).toBe(false);
    });

    test("boolean is refused -- it renders as untranslated True/False", () => {
        expect(isRenderableFieldType({ type: "boolean" })).toBe(false);
    });

    test("x2many has no scalar form", () => {
        expect(isRenderableFieldType({ type: "one2many" })).toBe(false);
        expect(isRenderableFieldType({ type: "many2many" })).toBe(false);
    });

    test("html is fine in a body and wrong in a subject", () => {
        expect(isRenderableFieldType({ type: "html" })).toBe(true);
        expect(isRenderableFieldType({ type: "html" }, { plainText: true })).toBe(
            false,
        );
    });

    test("a property separator is not a value", () => {
        expect(isRenderableFieldType({ type: "separator", is_property: true })).toBe(
            false,
        );
    });

    test("an unstored compute is renderable -- `searchable` was the wrong proxy", () => {
        expect(isRenderableFieldType({ type: "char", searchable: false })).toBe(true);
    });
});
