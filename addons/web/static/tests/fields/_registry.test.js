// @ts-check

import "@web/fields/field";

import { describe, expect, test } from "@odoo/hoot";
import { Component } from "@odoo/owl";
import { patchWithCleanup, serverState } from "@web/../tests/web_test_helpers";
import { Registry, registry } from "@web/core/registry";
import { fieldKey, registerField } from "@web/fields/_registry";
import { floatField } from "@web/fields/basic/float/float_field";
import { integerField } from "@web/fields/basic/integer/integer_field";
import { many2ManyTagsField } from "@web/fields/relational/many2many_tags/many2many_tags_field";

describe.current.tags("headless");

const fieldsRegistry = registry.category("fields");

const SENTINEL_PREFIX = "__test_registerField_";

function _sentinelWidget(/** @type {string} */ label) {
    return { component: class extends Component {}, displayName: label };
}

test("fieldKey composes view + name", () => {
    expect(fieldKey({ name: "text" })).toBe("text");
    expect(fieldKey({ name: "text", view: "list" })).toBe("list.text");
});

test("registerField legacy string form binds primary key", () => {
    const widget = _sentinelWidget("legacy_string");
    const key = `${SENTINEL_PREFIX}legacy_string`;
    try {
        registerField(key, widget);
        expect(fieldsRegistry.get(key)).toBe(widget);
    } finally {
        fieldsRegistry.remove(key);
    }
});

test("registerField spec form binds composed key", () => {
    const widget = _sentinelWidget("spec_form");
    const key = `list.${SENTINEL_PREFIX}spec_form`;
    try {
        registerField({ name: `${SENTINEL_PREFIX}spec_form`, view: "list" }, widget);
        expect(fieldsRegistry.get(key)).toBe(widget);
    } finally {
        fieldsRegistry.remove(key);
    }
});

test("registerField aliases bind same widget under each alias key", () => {
    const widget = _sentinelWidget("aliased");
    const primary = `${SENTINEL_PREFIX}primary`;
    const stringAlias = `${SENTINEL_PREFIX}alias_string`;
    const specAlias = `list.${SENTINEL_PREFIX}alias_spec`;
    try {
        registerField(
            {
                name: primary,
                aliases: [
                    stringAlias,
                    { name: `${SENTINEL_PREFIX}alias_spec`, view: "list" },
                ],
            },
            widget,
        );
        expect(fieldsRegistry.get(primary)).toBe(widget);
        expect(fieldsRegistry.get(stringAlias)).toBe(widget);
        expect(fieldsRegistry.get(specAlias)).toBe(widget);
    } finally {
        fieldsRegistry.remove(primary);
        fieldsRegistry.remove(stringAlias);
        fieldsRegistry.remove(specAlias);
    }
});

test("registerField returns the widget for chaining", () => {
    const widget = _sentinelWidget("chained");
    const key = `${SENTINEL_PREFIX}chained`;
    try {
        const returned = registerField(key, widget);
        expect(returned).toBe(widget);
    } finally {
        fieldsRegistry.remove(key);
    }
});

test("registerField with empty aliases array is a no-op beyond primary", () => {
    const widget = _sentinelWidget("empty_aliases");
    const primary = `${SENTINEL_PREFIX}empty_aliases`;
    try {
        registerField({ name: primary, aliases: [] }, widget);
        expect(fieldsRegistry.get(primary)).toBe(widget);
        const sentinelKeys = fieldsRegistry
            .getEntries()
            .map(([k]) => k)
            .filter((k) => k.startsWith(SENTINEL_PREFIX));
        expect(sentinelKeys).toEqual([primary]);
    } finally {
        fieldsRegistry.remove(primary);
    }
});

test("aliases form does NOT bind a variant widget to alias keys", () => {
    const base = _sentinelWidget("base");
    const variant = _sentinelWidget("variant");
    const baseKey = `${SENTINEL_PREFIX}base`;
    const variantKey = `form.${SENTINEL_PREFIX}variant`;
    try {
        registerField(
            {
                name: baseKey,
                aliases: [{ name: `${SENTINEL_PREFIX}variant`, view: "form" }],
            },
            base,
        );
        expect(fieldsRegistry.get(variantKey)).toBe(base);
        expect(fieldsRegistry.get(variantKey)).not.toBe(variant);
    } finally {
        fieldsRegistry.remove(baseKey);
        fieldsRegistry.remove(variantKey);
    }
});

/** @returns {Registry<any>} */
function _makeSchemaRegistry() {
    const schema = fieldsRegistry.validationSchema;
    expect(schema).not.toBe(null);
    const raw = new Registry("__test_fields_schema__");
    raw.addValidation(/** @type {any} */ (schema));
    return raw;
}

function _schemaComponent() {
    return class extends Component {};
}

test("fields schema rejects malformed declarations (debug: fail-fast)", () => {
    serverState.debug = "1";
    const raw = _makeSchemaRegistry();
    expect(() =>
        raw.add("bad_option_element", {
            component: _schemaComponent(),
            supportedOptions: ["not-an-object"],
        }),
    ).toThrow();
    expect(() =>
        raw.add("bad_option_no_name", {
            component: _schemaComponent(),
            supportedOptions: [{ label: "Nameless", type: "boolean" }],
        }),
    ).toThrow();
    expect(() =>
        raw.add("bad_option_name_type", {
            component: _schemaComponent(),
            supportedOptions: [{ name: 42, type: "boolean" }],
        }),
    ).toThrow();
    expect(() =>
        raw.add("bad_related_no_name", {
            component: _schemaComponent(),
            relatedFields: [{ type: "char" }],
        }),
    ).toThrow();
    expect(raw.getEntries().length).toBe(0);
});

test("fields schema quarantines a malformed declaration in non-debug", () => {
    const raw = _makeSchemaRegistry();
    /** @type {any[][]} */
    const warnings = [];
    patchWithCleanup(console, { warn: (...args) => warnings.push(args) });
    expect(() =>
        raw.add("bad_option_element", {
            component: _schemaComponent(),
            supportedOptions: ["not-an-object"],
        }),
    ).not.toThrow();
    expect(raw.contains("bad_option_element")).toBe(false);
    expect(warnings.length).toBe(1);
    expect(warnings[0][0]).toInclude(`Validation error for key "bad_option_element"`);
});

test("fields schema accepts representative real widget declarations", () => {
    serverState.debug = "1";
    const raw = _makeSchemaRegistry();
    expect(() => raw.add("float", floatField)).not.toThrow();
    expect(() => raw.add("integer", integerField)).not.toThrow();
    expect(() => raw.add("many2many_tags", many2ManyTagsField)).not.toThrow();
    expect(raw.contains("float")).toBe(true);
    expect(raw.contains("integer")).toBe(true);
    expect(raw.contains("many2many_tags")).toBe(true);
});

test("fields schema tolerates real-world declaration variance", () => {
    serverState.debug = "1";
    const raw = _makeSchemaRegistry();
    const widget = {
        component: _schemaComponent(),
        supportedOptions: [
            [{ label: "Nested", name: "nested", type: "string" }],
            { label: "Color", name: "color", type: "string", default: {} },
            {
                label: "Format",
                name: "numeric_format",
                type: "selection",
                choices: [{ label: "Jan 31, %s", value: false }],
                placeholder: "Jan 31, %s",
            },
            { name: "ribbon", type: "boolean" },
        ],
        relatedFields: [
            { name: "currency_id", type: "many2one", relation: "res.currency" },
            { name: "employee_salary_amount" },
        ],
    };
    expect(() => raw.add("variance", widget)).not.toThrow();
    expect(raw.contains("variance")).toBe(true);
});
