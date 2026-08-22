// @ts-check
/** @odoo-module native */

import { validate } from "@odoo/owl";

/**
 * @type {Record<string, any>}
 */
export const SEARCH_PARAMS_SCHEMA = {
    context: { type: Object, optional: true },
    domain: { type: Array, optional: true },
    groupBy: { type: Array, element: String, optional: true },
    orderBy: {
        type: Array,
        element: {
            type: Object,
            shape: {
                name: String,
                asc: { type: Boolean, optional: true },
            },
        },
        optional: true,
    },
};

/**
 * @param {any} payload
 * @returns {string[]}
 */
export function validateSearchParams(payload) {
    if (!payload || typeof payload !== "object") {
        return ["search params must be a plain object"];
    }
    const issues = [];
    /** @type {Record<string, any>} */
    const knownParams = {};
    for (const key of Object.keys(payload)) {
        if (Object.hasOwn(SEARCH_PARAMS_SCHEMA, key)) {
            knownParams[key] = payload[key];
        } else {
            issues.push(
                `unknown field '${key}' — add it to SEARCH_PARAMS_SCHEMA ` +
                    `at model/search_params_schema.js or remove the writer`,
            );
        }
    }
    try {
        validate(knownParams, SEARCH_PARAMS_SCHEMA);
    } catch (error) {
        issues.push(String(error.message ?? error));
    }
    return issues;
}
