// @ts-check

// Side-effect import: installs the fields registry validation schema
// (fieldRegistry.addValidation in field.js) that the schema tests below
// exercise.
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

// Sentinel widget objects keyed under names that no production code uses,
// so each test runs in isolation against the live (shared) fields registry
// without colliding with the canonical widget set.
const SENTINEL_PREFIX = "__test_registerField_";

function _sentinelWidget(label) {
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
        // All three keys resolve to the same widget object — reference
        // equality, not just structural equality.
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
        // Nothing else changed under the sentinel prefix — sanity assertion
        // that an empty aliases array does not silently bind unintended keys.
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
    // Intentional limitation: widgets that share a base but customize
    // behaviour (e.g. many2ManyTagsField vs. many2ManyTagsFieldColorEditable)
    // must be registered with separate registerField calls — chaining the
    // variant via ``aliases`` would silently bind the alias key to the BASE.
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
        // Pins down the actual (mis-)behaviour so callers know what to expect
        // if they misuse aliases for variant registration.
        expect(fieldsRegistry.get(variantKey)).toBe(base);
        expect(fieldsRegistry.get(variantKey)).not.toBe(variant);
    } finally {
        fieldsRegistry.remove(baseKey);
        fieldsRegistry.remove(variantKey);
    }
});

// Fields registry validation schema (installed by @web/fields/field)
//
// The schema QUARANTINES failing entries in production (see
// @web/core/registry ``validateSchema``: refused + beaconed, or thrown in
// debug mode), so these tests pin down both directions: malformed
// registrations are rejected, and every real-world declaration pattern found
// in community / enterprise / agromarin is accepted.
//
// Hoot patches ``Registry.prototype.add`` to force ``force: true``
// (module_set.hoot.js), but validation runs BEFORE that shortcut, so ``add``
// still validates. Tests use a fresh raw ``Registry`` seeded with the
// production schema object so they can't pollute the live fields registry.

/** @returns {Registry<any>} a raw registry validating with the REAL fields schema */
function _makeSchemaRegistry() {
    const schema = fieldsRegistry.validationSchema;
    // Guard: the schema must have been installed by the field.js import.
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
    // supportedOptions element that is not an object.
    expect(() =>
        raw.add("bad_option_element", {
            component: _schemaComponent(),
            supportedOptions: ["not-an-object"],
        }),
    ).toThrow();
    // Option entry missing the one universal key: ``name``.
    expect(() =>
        raw.add("bad_option_no_name", {
            component: _schemaComponent(),
            supportedOptions: [{ label: "Nameless", type: "boolean" }],
        }),
    ).toThrow();
    // Option entry whose ``name`` is not a string.
    expect(() =>
        raw.add("bad_option_name_type", {
            component: _schemaComponent(),
            supportedOptions: [{ name: 42, type: "boolean" }],
        }),
    ).toThrow();
    // relatedFields array-literal entry missing ``name``.
    expect(() =>
        raw.add("bad_related_no_name", {
            component: _schemaComponent(),
            relatedFields: [{ type: "char" }],
        }),
    ).toThrow();
    // Debug mode throws before insertion — nothing may have landed.
    expect(raw.getEntries().length).toBe(0);
});

test("fields schema quarantines a malformed declaration in non-debug", () => {
    // Production path: the invalid entry is REFUSED (not inserted) and a
    // structured warning is emitted — the page must not crash.
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
    // floatField: supportedOptions with a BOOLEAN ``default`` (the old,
    // dead shape declared ``default: String`` and would have quarantined
    // it fleet-wide had it ever activated).
    expect(() => raw.add("float", floatField)).not.toThrow();
    // integerField: NUMBER ``default`` (0).
    expect(() => raw.add("integer", integerField)).not.toThrow();
    // many2ManyTagsField: ``isRelationalField`` option key + FUNCTION-form
    // relatedFields (the old shape misplaced ``optional: true`` as a shape
    // key, making ``selection`` mandatory for array literals).
    expect(() => raw.add("many2many_tags", many2ManyTagsField)).not.toThrow();
    expect(raw.contains("float")).toBe(true);
    expect(raw.contains("integer")).toBe(true);
    expect(raw.contains("many2many_tags")).toBe(true);
});

test("fields schema tolerates real-world declaration variance", () => {
    // Patterns found by the 2026-07 sweep of community / enterprise /
    // agromarin that a naively strict schema would quarantine.
    serverState.debug = "1";
    const raw = _makeSchemaRegistry();
    const widget = {
        component: _schemaComponent(),
        supportedOptions: [
            // stock_action_field: nested Object.values(...) array (not
            // spread) as a supportedOptions element.
            [{ label: "Nested", name: "nested", type: "string" }],
            // hr_skills formatted_date: OBJECT default.
            { label: "Color", name: "color", type: "string", default: {} },
            // dateTimeField: boolean ``choices[].value`` + extra
            // ``placeholder`` key.
            {
                label: "Format",
                name: "numeric_format",
                type: "selection",
                choices: [{ label: "Jan 31, %s", value: false }],
                placeholder: "Jan 31, %s",
            },
            // hr_recruitment_integration_base (enterprise): no ``label``.
            { name: "ribbon", type: "boolean" },
        ],
        relatedFields: [
            // ``relation`` key (documents/knowledge widgets); ``type``
            // stays optional.
            { name: "currency_id", type: "many2one", relation: "res.currency" },
            { name: "employee_salary_amount" },
        ],
    };
    expect(() => raw.add("variance", widget)).not.toThrow();
    expect(raw.contains("variance")).toBe(true);
});
