// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { getSupportedOptionNames } from "@web/fields/field";
import { parseFieldNode, resetUnknownOptionWarnings } from "@web/views/field_arch";

describe.current.tags("headless");

/**
 * An arch option a widget does not declare is dropped in silence — the prop is
 * simply never set and the default stands. Scanning a 93-module database found
 * nine such pairs in shipped views (`no_open` on `many2many_tags`, `safe` on
 * `html`, `not_delete` on `many2many_tags`), every one of them inert.
 */

const MODELS = {
    "res.partner": {
        fields: {
            name: { type: "char", string: "Name" },
            active: { type: "boolean", string: "Active" },
            parent_id: { type: "many2one", relation: "res.partner", string: "Parent" },
        },
    },
};

/**
 * @param {string} arch
 * @returns {string[]} the warnings emitted while parsing
 */
function parseWithWarnings(arch) {
    /** @type {any[]} */
    const warnings = [];
    patchWithCleanup(console, { warn: (message) => warnings.push(String(message)) });
    patchWithCleanup(odoo, { debug: "1" });
    resetUnknownOptionWarnings();
    const node = /** @type {Element} */ (
        new DOMParser().parseFromString(arch, "text/xml").documentElement
    );
    parseFieldNode(node, MODELS, "res.partner", "form");
    return warnings;
}

describe("getSupportedOptionNames", () => {
    test("flattens descriptors and grouped descriptor arrays", () => {
        expect([
            ...(getSupportedOptionNames({
                supportedOptions: [{ name: "a" }, [{ name: "b" }, { name: "c" }]],
            }) || []),
        ]).toEqual(["a", "b", "c"]);
    });

    test("undeclared is null, not an empty set", () => {
        // The distinction is load-bearing: an empty set would mean "accepts no
        // option" and would report every option an undeclared widget reads.
        expect(getSupportedOptionNames({})).toBe(null);
        expect(getSupportedOptionNames({ supportedOptions: [] })).toEqual(new Set());
    });
});

describe("unknown field options", () => {
    test("an undeclared option is reported", () => {
        const warnings = parseWithWarnings(
            `<field name="parent_id" widget="many2one" options="{'no_such_option': True}"/>`,
        );
        expect(warnings.length).toBe(1);
        expect(warnings[0]).toInclude('"no_such_option"');
        expect(warnings[0]).toInclude("many2one");
    });

    test("a declared option is not reported", () => {
        // Guards the inverse failure: a check that reports everything is as
        // useless as one that reports nothing.
        expect(
            parseWithWarnings(
                `<field name="parent_id" widget="many2one" options="{'no_open': True}"/>`,
            ),
        ).toEqual([]);
    });

    test("a framework-level option is not reported", () => {
        expect(
            parseWithWarnings(
                `<field name="parent_id" widget="many2one" options="{'group_by_tooltip': 'x'}"/>`,
            ),
        ).toEqual([]);
    });

    test("a widget declaring nothing is left alone", () => {
        // `boolean` declares no supportedOptions, so its options cannot be
        // judged. 78 of the 228 registry keys are in this position.
        expect(
            parseWithWarnings(
                `<field name="active" widget="boolean" options="{'whatever': 1}"/>`,
            ),
        ).toEqual([]);
    });

    test("nothing is reported outside debug mode", () => {
        /** @type {any[]} */
        const warnings = [];
        patchWithCleanup(console, {
            warn: (message) => warnings.push(String(message)),
        });
        patchWithCleanup(odoo, { debug: "" });
        resetUnknownOptionWarnings();
        const node = /** @type {Element} */ (
            new DOMParser().parseFromString(
                `<field name="parent_id" widget="many2one" options="{'no_such_option': True}"/>`,
                "text/xml",
            ).documentElement
        );
        parseFieldNode(node, MODELS, "res.partner", "form");
        expect(warnings).toEqual([]);
    });

    test("the same widget/option pair is reported once", () => {
        /** @type {any[]} */
        const warnings = [];
        patchWithCleanup(console, {
            warn: (message) => warnings.push(String(message)),
        });
        patchWithCleanup(odoo, { debug: "1" });
        resetUnknownOptionWarnings();
        const arch = `<field name="parent_id" widget="many2one" options="{'no_such_option': True}"/>`;
        for (let i = 0; i < 3; i++) {
            const node = /** @type {Element} */ (
                new DOMParser().parseFromString(arch, "text/xml").documentElement
            );
            parseFieldNode(node, MODELS, "res.partner", "form");
        }
        expect(warnings.length).toBe(1);
    });
});
