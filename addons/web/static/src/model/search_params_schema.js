// @ts-check
/** @odoo-module native */

/** @module @web/model/search_params_schema - Runtime schema + validator for the SearchModel → Model boundary */

import { validate } from "@odoo/owl";

/**
 * The closed set of fields that flow from {@link SearchModel} into
 * {@link Model.load} via the
 * ``useModel(...) → getSearchParams(props) → model.load(params)``
 * boundary.
 *
 * Specifically, this schema describes the payload built by
 * ``getSearchParams`` in ``model/model.js``, which copies the four
 * ``SEARCH_KEYS`` from component props
 * (``core/constants.js:SEARCH_KEYS``).  Other fields that downstream
 * model code reads (``resId``, ``resIds``, ``resModel``,
 * ``useSampleModel``, ``comparison``) reach ``model.load`` through
 * *different* code paths — direct controller calls, model constructor
 * params, view-prop propagation — and are NOT validated here.
 *
 * The historical typedef at ``@web/model/types:SearchParams`` is the
 * union of all these paths and carries an open ``[key: string]: any``
 * escape hatch.  This schema is the *closed* counterpart for the
 * single boundary the validator can observe; the typedef stays as
 * documentation of the broader contract.
 *
 * Adding a new SEARCH_KEY is a deliberate, observable action: edit
 * ``core/constants.js`` AND this schema in the same PR.  The
 * validator catches one-sided drift.
 *
 * The shape mirrors OWL's ``validate()`` schema dialect (the same one
 * used by ``Registry.addValidation`` — see
 * ``core/registry.js:validateSchema``). All fields are optional
 * because ``getSearchParams`` always writes the same four keys but
 * the source props may have undefined values when not set (e.g.
 * mono-record loads where no SearchModel is mounted).
 *
 * @type {Record<string, any>}
 */
export const SEARCH_PARAMS_SCHEMA = {
    // OWL's validator treats ``Object`` very loosely (any non-array
    // non-null object), which is the right semantics for ``context``
    // since it is a free-form Python dict.
    context: { type: Object, optional: true },
    domain: { type: Array, optional: true },
    groupBy: { type: Array, element: String, optional: true },
    orderBy: {
        type: Array,
        element: {
            type: Object,
            shape: {
                name: String,
                // ``asc`` is optional in OrderTerm — some legacy callers
                // pass ``{ name }`` without an explicit direction and
                // rely on a downstream default.
                asc: { type: Boolean, optional: true },
            },
        },
        optional: true,
    },
};

/**
 * Validate a payload against {@link SEARCH_PARAMS_SCHEMA}, returning
 * a flat list of issue strings rather than throwing.  Caller decides
 * what to do with the issues — production code emits ``console.warn``
 * so a single drift doesn't crash a session, tests assert on the
 * array contents.
 *
 * Two issue classes:
 *
 *   1. **Shape mismatch** — OWL's validator raised. Wrapped error
 *      message goes into the issues list.
 *
 *   2. **Unknown field** — present in the payload but absent from
 *      the schema. Detected by a key-set diff so each unknown
 *      surfaces as its own actionable line for the
 *      ``[search-params]`` console-warn output (see the partition
 *      note in the function body for why OWL does not report these).
 *
 * @param {any} payload The object passed to ``Model.load``.
 * @returns {string[]} Empty array when valid.
 */
export function validateSearchParams(payload) {
    if (!payload || typeof payload !== "object") {
        return ["search params must be a plain object"];
    }
    const issues = [];
    // Partition the payload: recognized keys are shape-checked by OWL,
    // unrecognized keys get the friendlier per-field message below.
    // Validating only the known subset stops OWL from also emitting its
    // own lumped "unknown key 'X'" string, which would otherwise
    // double-report every unknown field — once by OWL, once by the diff.
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
