// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";
import { evaluateExpr } from "@web/core/py_js/py";
import { deepEqual, shallowEqual } from "@web/core/utils/collections/objects";

/**
 * @param {Object} record
 * @param {string} fieldName
 * @param {string} [rawContext]
 * @returns {Object}
 */
const CONTEXT_MEMO = new WeakMap();

function computeFieldContext(record, fieldName, rawContext) {
    const context = {};
    for (const key of Object.keys(record.context)) {
        if (
            !key.startsWith("default_") &&
            !key.startsWith("search_default_") &&
            !key.endsWith("_view_ref")
        ) {
            context[key] = record.context[key];
        }
    }

    // The arch expression is evaluated against the record's evalContext as it
    // is, not a copy: the interpreter reads names by property access, so a
    // Field evaluating this during its render subscribes to the fields the
    // expression names and nothing else. makeContext spreads the evaluation
    // context first, which reads every key and re-renders the Field -- and
    // whatever it hands the context to -- on any edit of the record.
    const archContext =
        rawContext && rawContext !== "{}"
            ? evaluateExpr(rawContext, record.evalContext)
            : {};
    return {
        ...context,
        ...record.fields[fieldName].context,
        ...archContext,
    };
}

export function getFieldContext(
    record,
    fieldName,
    rawContext = record.activeFields[fieldName].context,
) {
    const fresh = computeFieldContext(record, fieldName, rawContext);
    let byKey = CONTEXT_MEMO.get(record);
    if (!byKey) {
        byKey = new Map();
        CONTEXT_MEMO.set(record, byKey);
    }
    const key = `${fieldName} ${rawContext ?? ""}`;
    const previous = byKey.get(key);
    if (previous && shallowEqual(previous, fresh, deepEqual)) {
        return previous;
    }
    byKey.set(key, fresh);
    return fresh;
}

/**
 * @param {Object} record
 * @param {string} fieldName
 * @param {*} domain
 * @returns {*}
 */
export function getFieldDomain(record, fieldName, domain) {
    if (typeof domain === "function") {
        domain = domain(record);
    }
    if (domain) {
        return domain;
    }
    domain = record.fields[fieldName].domain;
    return typeof domain === "string"
        ? new Domain(evaluateExpr(domain, record.evalContext)).toList()
        : domain || [];
}

/**
 * @param {{ context: Record<string, any> }} config
 * @returns {{ context: Object, uid: number, allowed_company_ids: number[], current_company_id: number | undefined }}
 */
export function getBasicEvalContext(config) {
    const { uid, allowed_company_ids } = config.context;
    return {
        context: config.context,
        uid,
        allowed_company_ids,
        current_company_id: allowed_company_ids?.[0],
    };
}

/**
 * @param {{ context: Record<string, any> }} config
 * @returns {Record<string, any>}
 */
export function getSpecEvalContext(config) {
    return { ...config.context, ...getBasicEvalContext(config) };
}

let nextId = 0;
/**
 * @param {string} [prefix]
 * @returns {string}
 */
export function getId(prefix = "") {
    return `${prefix}_${++nextId}`;
}

/**
 * @param {any} field
 * @returns {boolean}
 */
export function isRelational(field) {
    return field && ["one2many", "many2many", "many2one"].includes(field.type);
}
