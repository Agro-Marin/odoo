import { search, simplifyString } from "@api_doc/utils/doc_model_search";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

const MODELS = [
    {
        model: "res.partner",
        name: "Contact",
        fields: { vat: { string: "Tax ID" } },
        methods: ["name_search"],
    },
    {
        model: "ir.cron",
        name: "Scheduled Actions",
        fields: {},
        methods: ["method_direct_trigger"],
    },
];
const ALL = { models: true, fields: true, methods: true };

describe("simplifyString", () => {
    test("punctuation and case are dropped", () => {
        expect(simplifyString(" Res.Partner ")).toBe("respartner");
    });

    test("nullish input is an empty string, not a crash", () => {
        expect(simplifyString(undefined)).toBe("");
        expect(simplifyString(null)).toBe("");
    });
});

describe("search", () => {
    test("an empty query matches nothing", () => {
        // Otherwise every model in the registry scores as a match and the
        // modal renders the whole database.
        expect(search(MODELS, "", ALL)).toEqual([]);
        expect(search(MODELS, "   ", ALL)).toEqual([]);
    });

    test("a model is found by technical name and by label", () => {
        expect(search(MODELS, "respartner", ALL).some((r) => r.type === "model")).toBe(
            true,
        );
        expect(search(MODELS, "contact", ALL).some((r) => r.type === "model")).toBe(
            true,
        );
    });

    test("punctuation in the query does not prevent a match", () => {
        expect(search(MODELS, "res.partner", ALL).some((r) => r.type === "model")).toBe(
            true,
        );
    });

    test("filters exclude a whole result kind", () => {
        const results = search(MODELS, "namesearch", { ...ALL, methods: false });
        expect(results.some((r) => r.type === "method")).toBe(false);
    });

    test("fields and methods are reachable", () => {
        expect(search(MODELS, "vat", ALL).some((r) => r.type === "field")).toBe(true);
        expect(search(MODELS, "namesearch", ALL).some((r) => r.type === "method")).toBe(
            true,
        );
    });

    test("an exact model match outranks a longer incidental one", () => {
        const results = search(MODELS, "ircron", ALL);
        expect(results[0].model.model).toBe("ir.cron");
    });
});
