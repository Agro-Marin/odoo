// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { fieldKey, registerField } from "@web/fields/_registry";

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
    // Documents intentional limitation: when two widgets share a base but
    // customize behaviour (e.g. many2ManyTagsField vs.
    // many2ManyTagsFieldColorEditable), they MUST be registered with separate
    // registerField calls. Chaining the variant via ``aliases`` would silently
    // bind the alias key to the BASE widget — the opposite of the intent.
    const base = _sentinelWidget("base");
    const variant = _sentinelWidget("variant");
    const baseKey = `${SENTINEL_PREFIX}base`;
    const variantKey = `form.${SENTINEL_PREFIX}variant`;
    try {
        registerField({ name: baseKey, aliases: [{ name: `${SENTINEL_PREFIX}variant`, view: "form" }] }, base);
        // The variant key now (incorrectly, for this hypothetical caller) points to BASE.
        // We assert the helper's actual behaviour so callers know what they get if they
        // misuse aliases for variant registration.
        expect(fieldsRegistry.get(variantKey)).toBe(base);
        expect(fieldsRegistry.get(variantKey)).not.toBe(variant);
    } finally {
        fieldsRegistry.remove(baseKey);
        fieldsRegistry.remove(variantKey);
    }
});
