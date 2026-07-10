// @ts-check

import "@web/fields/formatters";
import "@web/fields/parsers";
import "@web/model/relational_model/field_values"; // registers deserializers
import "@web/model/relational_model/record_value_transforms"; // registers serializers

import { beforeEach, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { getFieldCodec, hasFieldCodec } from "@web/core/field_codec";
import { registry } from "@web/core/registry";

beforeEach(makeMockEnv);

test("every formatter type yields a complete {format, parse} codec", () => {
    const types = registry
        .category("formatters")
        .getEntries()
        .map(([key]) => key);
    expect(types.length).toBeGreaterThan(8); // many more formatters than the 8 parsers
    for (const type of types) {
        const codec = getFieldCodec(type);
        expect(typeof codec.format).toBe("function");
        expect(typeof codec.parse).toBe("function");
    }
});

test("parse delegates to the registered parser when one exists", () => {
    expect(getFieldCodec("integer").parse("1,000")).toBe(1000);
    expect(getFieldCodec("float").parse("12.5")).toBe(12.5);
    expect(getFieldCodec("integer").parseable).toBe(true);
});

test("free-text types (char/text/html) parse as identity and are parseable", () => {
    // Identity parse: the string IS the value. Whitespace handling (char's
    // `trim` option) is a widget concern, deliberately not done by the codec.
    for (const type of ["char", "text", "html"]) {
        const codec = getFieldCodec(type);
        expect(codec.parse("  hi  ")).toBe("  hi  ");
        expect(codec.parseable).toBe(true);
    }
});

test("non-text types parse as identity and are not parseable", () => {
    // a native (non-string) value such as a many2one tuple/record — parse is identity
    /** @type {any} */
    const value = { id: 1, display_name: "Rec" };
    for (const type of ["selection", "boolean", "many2one", "many2many"]) {
        const codec = getFieldCodec(type);
        expect(codec.parse(value)).toBe(value);
        expect(codec.parseable).toBe(false);
        expect(typeof codec.format).toBe("function");
    }
});

test("scalar text/number types format to a string", () => {
    expect(typeof getFieldCodec("char").format("x")).toBe("string");
    expect(typeof getFieldCodec("integer").format(1000)).toBe("string");
    expect(typeof getFieldCodec("float").format(1.5)).toBe("string");
});

test("unknown type is total: string format, identity parse, no codec coverage", () => {
    const codec = getFieldCodec("totally_made_up_type");
    expect(codec.format(5)).toBe("5");
    expect(codec.format(false)).toBe("");
    expect(codec.parse("x")).toBe("x");
    expect(hasFieldCodec("totally_made_up_type")).toBe(false);
    expect(hasFieldCodec("char")).toBe(true);
});

test("codec reads the registries live — later registrations are honored", () => {
    const parsers = registry.category("parsers");
    expect(getFieldCodec("char").parse("  x  ")).toBe("  x  "); // identity fallback
    parsers.add("char", (value) => `PARSED:${value}`);
    try {
        expect(getFieldCodec("char").parse("  x  ")).toBe("PARSED:  x  ");
    } finally {
        parsers.remove("char");
    }
    expect(getFieldCodec("char").parse("  x  ")).toBe("  x  "); // back to identity
});

test("extractOptions delegates to the formatter static, {} when none/unknown", () => {
    const fieldInfo = { attrs: {}, options: {} };
    // numeric/text formatters declare an extractOptions static -> object
    expect(typeof getFieldCodec("integer").extractOptions(fieldInfo)).toBe("object");
    expect(typeof getFieldCodec("char").extractOptions(fieldInfo)).toBe("object");
    // formatters without the static, and unknown types -> {}
    expect(getFieldCodec("boolean").extractOptions(fieldInfo)).toEqual({});
    expect(getFieldCodec("totally_made_up_type").extractOptions(fieldInfo)).toEqual({});
});

test("serialize/deserialize are transport conversion shared with the model layer", () => {
    // read-rich / write-lean asymmetry for relational types
    const m2o = getFieldCodec("many2one");
    expect(m2o.deserialize([5, "Partner X"], { type: "many2one" })).toEqual({
        id: 5,
        display_name: "Partner X",
    });
    expect(m2o.serialize({ id: 5, display_name: "Partner X" })).toBe(5);

    const ref = getFieldCodec("reference");
    expect(
        ref.deserialize(
            { id: { id: 7, model: "res.users" }, display_name: "U" },
            { type: "reference" },
        ),
    ).toEqual({
        resId: 7,
        resModel: "res.users",
        displayName: "U",
    });
    expect(ref.serialize({ resModel: "res.users", resId: 7 })).toBe("res.users,7");

    // scalar round-trips, incl. the empty-char → false normalization
    const c = getFieldCodec("char");
    expect(c.serialize(c.deserialize("Hi", { type: "char" }))).toBe("Hi");
    expect(c.serialize(c.deserialize("", { type: "char" }))).toBe(false);

    // transport (serialize) is DISTINCT from UI (format) for the same value
    expect(m2o.serialize({ id: 5, display_name: "Partner X" })).not.toBe(
        m2o.format({ id: 5, display_name: "Partner X" }),
    );

    // unknown type: identity both directions
    expect(getFieldCodec("zzz").serialize(9)).toBe(9);
    expect(getFieldCodec("zzz").deserialize(9)).toBe(9);
});
