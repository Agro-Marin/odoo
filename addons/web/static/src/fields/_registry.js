// @ts-check
/** @odoo-module native */

/** @module @web/fields/_registry */

import { registry } from "@web/core/registry";

/**
 * @typedef {"list" | "form" | "kanban" | "calendar" | "hierarchy" | "base_settings"} FieldViewPrefix
 */

/**
 * @typedef {{
 *   name: string;
 *   view?: FieldViewPrefix;
 *   aliases?: Array<string | { name: string; view?: FieldViewPrefix }>;
 * }} FieldRegistrationSpec
 */

/**
 * @param {FieldRegistrationSpec} spec
 * @returns {string}
 */
export function fieldKey(spec) {
    return spec.view ? `${spec.view}.${spec.name}` : spec.name;
}

/**
 * @template {Partial<import("registries").FieldsRegistryItemShape>} T
 * @param {string | FieldRegistrationSpec} nameOrSpec
 * @param {T} widget
 * @param {...any} rest
 * @returns {T}
 */
export function registerField(nameOrSpec, widget, ...rest) {
    return _register(nameOrSpec, widget, rest, false);
}

/**
 * @template T
 * @param {string | FieldRegistrationSpec} nameOrSpec
 * @param {T} widget
 * @param {...any} rest
 * @returns {T}
 */
export function registerFallbackField(nameOrSpec, widget, ...rest) {
    return _register(nameOrSpec, widget, rest, true);
}

/**
 * @template T
 * @param {string | FieldRegistrationSpec} nameOrSpec
 * @param {T} widget
 * @param {any[]} rest
 * @param {boolean} onlyIfAbsent
 * @returns {T}
 */
function _register(nameOrSpec, widget, rest, onlyIfAbsent) {
    const fieldsReg = registry.category("fields");
    const addKey = (/** @type {string} */ key) => {
        if (onlyIfAbsent && fieldsReg.contains(key)) {
            return;
        }
        fieldsReg.add(key, /** @type {any} */ (widget), ...rest);
    };
    addKey(typeof nameOrSpec === "string" ? nameOrSpec : fieldKey(nameOrSpec));
    if (typeof nameOrSpec !== "string" && nameOrSpec.aliases?.length) {
        for (const alias of nameOrSpec.aliases) {
            addKey(typeof alias === "string" ? alias : fieldKey(alias));
        }
    }
    return widget;
}
