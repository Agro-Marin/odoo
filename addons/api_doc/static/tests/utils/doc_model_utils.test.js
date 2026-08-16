import {
    getCreateDict,
    getParameterDefaultValue,
} from "@api_doc/utils/doc_model_utils";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

describe("getParameterDefaultValue", () => {
    test("a declared default wins over everything", () => {
        expect(
            getParameterDefaultValue("limit", { default: 80, annotation: "int" }),
        ).toBe(80);
        expect(
            getParameterDefaultValue("order", { default: null, annotation: "str" }),
        ).toBe(null);
    });

    test("a domain gets a runnable domain, not an empty string", () => {
        // The server rejects "" outright: `Domain() invalid argument type for
        // domain: ''`. This used to be every domain parameter in the page,
        // because the lookup read `parameter.type`, a key that is not there.
        expect(
            getParameterDefaultValue("domain", { annotation: "DomainType" }),
        ).toEqual([["display_name", "ilike", "a%"]]);
        expect(
            getParameterDefaultValue("domain", { annotation: "DomainType | None" }),
        ).toEqual([["display_name", "ilike", "a%"]]);
    });

    test("scalars follow their annotation", () => {
        expect(getParameterDefaultValue("count", { annotation: "int" })).toBe(0);
        expect(getParameterDefaultValue("ratio", { annotation: "float" })).toBe(0);
        expect(getParameterDefaultValue("flag", { annotation: "bool" })).toBe(false);
        expect(getParameterDefaultValue("name", { annotation: "str" })).toBe("");
    });

    test("the OUTERMOST type decides the shape", () => {
        expect(
            getParameterDefaultValue("spec", { annotation: "dict[str, list[str]]" }),
        ).toEqual({});
        expect(getParameterDefaultValue("rows", { annotation: "list[dict]" })).toEqual(
            [],
        );
    });

    test("a dotted annotation is resolved by its last segment", () => {
        expect(
            getParameterDefaultValue("names", {
                annotation: "collections.abc.Sequence[str]",
            }),
        ).toEqual([]);
    });

    test("an unknown annotation falls back on the parameter name", () => {
        expect(getParameterDefaultValue("args", { annotation: "Whatever" })).toEqual(
            [],
        );
        expect(getParameterDefaultValue("thing", { annotation: "Whatever" })).toBe("");
        expect(getParameterDefaultValue("thing", {})).toBe("");
    });

    test("each call gets its own value to edit", () => {
        const first = getParameterDefaultValue("domain", { annotation: "DomainType" });
        first.push(["x", "=", 1]);
        expect(
            getParameterDefaultValue("domain", { annotation: "DomainType" }),
        ).toHaveLength(1);
    });
});

describe("getCreateDict", () => {
    test("only required fields are seeded", () => {
        const model = {
            fields: {
                name: { type: "char", required: true },
                comment: { type: "char", required: false },
            },
        };
        expect(getCreateDict(model)).toEqual({ name: "" });
    });

    test("a required date is a date, not the source of Date.now", () => {
        const model = {
            fields: {
                day: { type: "date", required: true },
                moment: { type: "datetime", required: true },
            },
        };
        const values = getCreateDict(model);
        expect(values.day).toMatch(/^\d{4}-\d{2}-\d{2}$/);
        expect(values.moment).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    });
});
