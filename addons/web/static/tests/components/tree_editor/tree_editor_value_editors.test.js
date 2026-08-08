// @ts-check

/**
 * `tree_editor_value_editors` decides, for every (field type, operator) pair the
 * domain/expression editors offer, which component edits the value and what a
 * fresh leaf starts out as. It had no direct tests: everything below was only
 * ever exercised incidentally, through whichever combinations the
 * domain_selector suites happen to build.
 */

import { expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { getDomainDisplayedOperators } from "@web/components/domain_selector/domain_selector_operator_editor";
import { getExpressionDisplayedOperators } from "@web/components/expression_editor/expression_editor_operator_editor";
import {
    getDefaultValue,
    getValueEditorInfo,
} from "@web/components/tree_editor/tree_editor_value_editors";

const FIELD_TYPES = [
    "boolean",
    "selection",
    "char",
    "text",
    "html",
    "date",
    "datetime",
    "integer",
    "float",
    "monetary",
    "many2one",
    "many2many",
    "one2many",
    "json",
    "binary",
    "properties",
    "tags",
];

/**
 * @param {string} type
 * @returns {Object} a field definition plausible enough for every editor
 */
function fieldDef(type) {
    const def = { name: "f", string: "F", type };
    if (type === "selection") {
        /** @type {any} */ (def).selection = [
            ["a", "A"],
            ["b", "B"],
        ];
    }
    if (["many2one", "many2many", "one2many"].includes(type)) {
        def.relation = "partner";
    }
    return def;
}

/**
 * The invariant: a freshly created leaf must be editable by the very editor
 * that created it. If `isSupported` rejects the default -- or `shouldResetValue`
 * immediately asks for it to be thrown away -- the user gets a condition the
 * tree editor reports as unsupported the moment it appears.
 *
 * @param {string} label
 * @param {(type: string) => string[]} getOperators
 */
function checkMatrix(label, getOperators) {
    const failures = [];
    for (const type of FIELD_TYPES) {
        const def = fieldDef(type);
        for (const operator of getOperators(type)) {
            let value;
            try {
                value = getDefaultValue(def, operator);
            } catch (error) {
                failures.push(`${label} ${type}/${operator}: threw ${error.message}`);
                continue;
            }
            const info = getValueEditorInfo(def, operator);
            if (!info.isSupported(value)) {
                failures.push(
                    `${label} ${type}/${operator}: default ${JSON.stringify(
                        value,
                    )} is not supported by its own editor`,
                );
            } else if (info.shouldResetValue?.(value)) {
                failures.push(
                    `${label} ${type}/${operator}: default ${JSON.stringify(
                        value,
                    )} asks to be reset immediately`,
                );
            }
        }
    }
    return failures;
}

test("every domain (type, operator) pair produces a default its own editor accepts", async () => {
    await makeMockEnv();
    expect(
        checkMatrix("domain", (type) => getDomainDisplayedOperators(fieldDef(type))),
    ).toEqual([]);
});

test("every expression (type, operator) pair produces a default its own editor accepts", async () => {
    await makeMockEnv();
    expect(
        checkMatrix("expression", (type) =>
            getExpressionDisplayedOperators(fieldDef(type)),
        ),
    ).toEqual([]);
});

test("an unknown field type still yields a usable editor", async () => {
    await makeMockEnv();
    // `getDomainDisplayedOperators(undefined)` answers ["="], and the tree
    // editor reaches here with no field definition whenever a path is invalid.
    const info = getValueEditorInfo(undefined, "=");
    const value = getDefaultValue(undefined, "=");
    expect(info.isSupported(value)).toBe(true);
    expect(typeof info.stringify).toBe("function");
});

test("getDefaultValue keeps a value the editor already supports", async () => {
    await makeMockEnv();
    const def = fieldDef("char");
    expect(getDefaultValue(def, "=", "kept")).toBe("kept");
    // ... and replaces one it does not.
    expect(getDefaultValue(def, "=", 42)).toBe("");
});

test("`between` derives its pair from the single-value default", async () => {
    await makeMockEnv();
    const info = getValueEditorInfo(fieldDef("integer"), "between");
    const value = getDefaultValue(fieldDef("integer"), "between");
    expect(Array.isArray(value)).toBe(true);
    expect(/** @type {any[]} */ (value).length).toBe(2);
    expect(info.isSupported(value)).toBe(true);
});

test("`between` resets a pair whose ends the element editor rejects", async () => {
    await makeMockEnv();
    // Checked on a date, whose element editor actually discriminates: the
    // numeric editors answer `isSupported: () => true` and delegate every
    // judgement to `shouldResetValue`, so they can never fail this way.
    const info = getValueEditorInfo(fieldDef("date"), "between");
    expect(info.shouldResetValue?.(["2019-03-11", "2019-03-12"])).toBe(false);
    expect(info.shouldResetValue?.(["2019-03-11", 42])).toBe(true);
});
