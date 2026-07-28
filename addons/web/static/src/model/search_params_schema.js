// @ts-check
/** @odoo-module native */

/** @module @web/model/search_params_schema - Runtime schema + validator for the SearchModel → Model boundary */

import { validate } from "@odoo/owl";

/**
 * Closed set of fields flowing from {@link SearchModel} into {@link Model.load}
 * via ``getSearchParams(props) → model.load(params)`` in ``model/model.js``,
 * which copies the four ``SEARCH_KEYS`` from ``core/constants.js``. Other
 * fields reaching ``model.load`` (``resId``, ``resIds``, ``resModel``,
 * ``useSampleModel``, ``comparison``) go through different paths and aren't
 * validated here; the broader open contract stays documented at
 * ``@web/model/types:SearchParams``.
 *
 * Adding a SEARCH_KEY means updating ``core/constants.js`` and this schema
 * together — the validator catches one-sided drift. Shape mirrors OWL's
 * ``validate()`` dialect. All fields are optional since ``getSearchParams``
 * may pass undefined when no SearchModel is mounted (e.g. mono-record loads).
 *
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
 * Validate a payload against {@link SEARCH_PARAMS_SCHEMA}, returning a flat
 * list of issue strings rather than throwing (production code console.warns
 * so a single drift doesn't crash a session). Two issue classes: shape
 * mismatches raised by OWL's validator, and unknown fields (present in the
 * payload but absent from the schema), each reported on its own line.
 *
 * @param {any} payload The object passed to ``Model.load``.
 * @returns {string[]} Empty array when valid.
 */
export function validateSearchParams(payload) {
    if (!payload || typeof payload !== "object") {
        return ["search params must be a plain object"];
    }
    const issues = [];
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
