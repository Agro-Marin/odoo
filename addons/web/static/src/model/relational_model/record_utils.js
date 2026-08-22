// @ts-check
/** @odoo-module native */

import { isX2Many } from "@web/core/field_types";
import { evaluateBooleanExpr, getExprFreeVariables } from "@web/core/py_js/py";

import { formatServerValue } from "./record_value_transforms.js";

/**
 * @param {string|false} expr
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function evaluateFieldAttr(expr, evalContext) {
    return expr ? evaluateBooleanExpr(expr, evalContext) : false;
}

/**
 * @param {Object} activeField
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function isFieldInvisible(activeField, evalContext) {
    return evaluateFieldAttr(activeField.invisible, evalContext);
}

/**
 * @param {Object} activeField
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function isFieldReadonly(activeField, evalContext) {
    return evaluateFieldAttr(activeField.readonly, evalContext);
}

/**
 * @param {Object} activeField
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function isFieldRequired(activeField, evalContext) {
    return evaluateFieldAttr(activeField.required, evalContext);
}

/**
 * @type {null}
 */
const UNKNOWN_DEPENDENCIES = null;

/**
 * @param {string|false|undefined} expr
 * @returns {Set<string>|null}
 */
export function extractFieldNamesFromExpr(expr) {
    if (!expr || typeof expr !== "string") {
        return new Set();
    }
    if (expr === "True" || expr === "False" || expr === "1" || expr === "0") {
        return new Set();
    }
    try {
        return getExprFreeVariables(expr);
    } catch {
        return UNKNOWN_DEPENDENCIES;
    }
}

/**
 * @type {WeakMap<object, { dependents: Map<string, Set<string>>, always: Set<string> }>}
 */
const _modifierDependencyCache = new WeakMap();

/**
 * @param {Object} activeFields
 */
export function invalidateModifierDependencies(activeFields) {
    _modifierDependencyCache.delete(activeFields);
}

/**
 * @param {Object} activeFields
 * @returns {{ dependents: Map<string, Set<string>>, always: Set<string> }}
 */
export function getModifierDependencies(activeFields) {
    let cached = _modifierDependencyCache.get(activeFields);
    if (cached) {
        return cached;
    }
    /** @type {Map<string, Set<string>>} */
    const dependents = new Map();
    /** @type {Set<string>} */
    const always = new Set();
    const fieldNames = Object.keys(activeFields);
    const fieldNameSet = new Set(fieldNames);
    for (const fieldB of fieldNames) {
        const af = activeFields[fieldB];
        const refs = new Set();
        let unknown = false;
        for (const modifier of [af.invisible, af.required, af.readonly]) {
            const names = extractFieldNamesFromExpr(modifier);
            if (names === UNKNOWN_DEPENDENCIES) {
                unknown = true;
                break;
            }
            for (const name of names) {
                refs.add(name);
            }
        }
        if (unknown) {
            always.add(fieldB);
            continue;
        }
        for (const name of refs) {
            if (name === fieldB || !fieldNameSet.has(name)) {
                continue;
            }
            let set = dependents.get(name);
            if (!set) {
                set = new Set();
                dependents.set(name, set);
            }
            set.add(fieldB);
        }
    }
    cached = { dependents, always };
    _modifierDependencyCache.set(activeFields, cached);
    return cached;
}

/**
 * @param {string[]} changedFieldNames
 * @param {Object} activeFields
 * @returns {Set<string>}
 */
export function computeRevalidationScope(changedFieldNames, activeFields) {
    const { dependents, always } = getModifierDependencies(activeFields);
    const scope = new Set(changedFieldNames);
    for (const changed of changedFieldNames) {
        const deps = dependents.get(changed);
        if (deps) {
            for (const b of deps) {
                scope.add(b);
            }
        }
    }
    for (const b of always) {
        scope.add(b);
    }
    return scope;
}

/**
 * @param {Object} params
 * @param {Object} params.changes
 * @param {Object} params.values
 * @param {boolean} params.isNew
 * @param {Object} params.fields
 * @param {Object} params.activeFields
 * @param {Object} params.evalContext
 * @param {Object} [params.options]
 * @param {boolean} [params.options.withReadonly]
 * @param {(fieldName: string, value: any, withReadonly: boolean) => any[]} params.getCommands
 * @returns {Object}
 */
export function computeChangeset({
    changes,
    values,
    isNew,
    fields,
    activeFields,
    evalContext,
    options = {},
    getCommands,
}) {
    const { withReadonly = false } = options;
    const effectiveChanges = isNew ? { ...values, ...changes } : changes;

    /** @type {Record<string, any>} */
    const result = {};

    for (const [fieldName, value] of Object.entries(effectiveChanges)) {
        const field = fields[fieldName];

        if (fieldName === "id") {
            continue;
        }

        if (
            !withReadonly &&
            fieldName in activeFields &&
            isFieldReadonly(activeFields[fieldName], evalContext) &&
            !activeFields[fieldName].forceSave
        ) {
            continue;
        }

        if (field.relatedPropertyField) {
            continue;
        }

        if (isX2Many(field)) {
            if (typeof value?._getCommands !== "function") {
                if (isNew) {
                    result[fieldName] = [];
                }
                continue;
            }
            const commands = getCommands(fieldName, value, withReadonly);
            if (!isNew && !commands.length && !withReadonly) {
                continue;
            }
            result[fieldName] = commands;
        } else {
            const serverValue = formatServerValue(field.type, value);
            if (serverValue === undefined) {
                continue;
            }
            result[fieldName] = serverValue;
        }
    }

    return result;
}
