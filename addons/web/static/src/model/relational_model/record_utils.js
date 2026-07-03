// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_utils - Pure utility functions for field attribute evaluation (invisible, readonly, required) */

/**
 * Pure utility functions extracted from Record.
 *
 * These functions encapsulate domain logic that was previously embedded
 * in Record methods but has zero dependency on OWL reactivity (no reactive,
 * markRaw, toRaw, or Component imports). They can be tested with plain
 * assert in <1ms without any browser or framework setup.
 *
 * @see record_value_transforms.js for value formatting and context building
 * @see record_validator.js for field validation logic
 */

import { evaluateBooleanExpr, getExprFreeVariables } from "@web/core/py_js/py";

import { formatServerValue } from "./record_value_transforms.js";
// ---------------------------------------------------------------------------
// Field attribute evaluation
// ---------------------------------------------------------------------------

/**
 * Evaluate a field attribute expression (invisible, readonly, required).
 *
 * This is the pure core of Record._isInvisible, _isReadonly, _isRequired.
 * Given a Python boolean expression string and an eval context, returns
 * whether the expression evaluates to true.
 *
 * @param {string|false} expr - Python boolean expression (e.g. "state == 'done'")
 * @param {Object} evalContext - record data context for expression evaluation
 * @returns {boolean}
 */
export function evaluateFieldAttr(expr, evalContext) {
    return expr ? evaluateBooleanExpr(expr, evalContext) : false;
}

/**
 * Check if a field is invisible given its active field definition and eval context.
 *
 * @param {Object} activeField - the activeFields[fieldName] entry
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function isFieldInvisible(activeField, evalContext) {
    return evaluateFieldAttr(activeField.invisible, evalContext);
}

/**
 * Check if a field is readonly given its active field definition and eval context.
 *
 * @param {Object} activeField - the activeFields[fieldName] entry
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function isFieldReadonly(activeField, evalContext) {
    return evaluateFieldAttr(activeField.readonly, evalContext);
}

/**
 * Check if a field is required given its active field definition and eval context.
 *
 * @param {Object} activeField - the activeFields[fieldName] entry
 * @param {Object} evalContext
 * @returns {boolean}
 */
export function isFieldRequired(activeField, evalContext) {
    return evaluateFieldAttr(activeField.required, evalContext);
}

// ---------------------------------------------------------------------------
// Modifier dependency analysis (scoped per-commit re-validation)
// ---------------------------------------------------------------------------

/**
 * Sentinel returned by {@link extractFieldNamesFromExpr} when the expression
 * cannot be statically analysed (parse failure). Callers must treat it as
 * "depends on everything" and fall back to unconditional re-validation.
 * @type {null}
 */
const UNKNOWN_DEPENDENCIES = null;

/**
 * Extract the field-name root identifiers referenced by a modifier expression
 * (``invisible`` / ``required`` / ``readonly``).
 *
 * Thin, defensive wrapper around {@link getExprFreeVariables}: returns the raw
 * free-variable root-name set on success (still including non-field names such
 * as ``parent``, ``context``, ``uid`` and builtin callees — the caller filters
 * those against the real field universe), or {@link UNKNOWN_DEPENDENCIES}
 * (``null``) when the expression is falsy or fails to parse. A ``null`` result
 * is the airtight-fallback signal: the field must then be re-validated on every
 * commit rather than risk missing a dependency.
 *
 * @param {string|false|undefined} expr
 * @returns {Set<string>|null} free-variable root names, or ``null`` if unknown
 */
export function extractFieldNamesFromExpr(expr) {
    if (!expr || typeof expr !== "string") {
        // No modifier (or a boolean literal already normalised away): no
        // dependency on any field.
        return new Set();
    }
    if (expr === "True" || expr === "False" || expr === "1" || expr === "0") {
        return new Set();
    }
    try {
        return getExprFreeVariables(expr);
    } catch {
        // Unparseable expression — cannot prove independence, so signal
        // "unknown" and let the caller conservatively always re-validate.
        return UNKNOWN_DEPENDENCIES;
    }
}

/**
 * Per-``activeFields`` cache of the modifier-dependency inverse map. Keyed on
 * the (arch-stable) ``activeFields`` object so extraction runs once per view
 * rather than once per commit. ``WeakMap`` lets the entry be collected when the
 * view (and its ``activeFields``) is torn down.
 *
 * @type {WeakMap<object, { dependents: Map<string, Set<string>>, always: Set<string> }>}
 */
const _modifierDependencyCache = new WeakMap();

/**
 * Build (and memoise) the inverse dependency map for a view's ``activeFields``:
 * for each field ``X``, the set of fields ``B`` whose ``invisible`` /
 * ``required`` / ``readonly`` modifier references ``X``.
 *
 * All three modifiers are considered:
 *   - ``invisible`` and ``required`` directly drive
 *     {@link findUnsetRequiredFields} (an invisible field is skipped; a
 *     non-required field is not flagged), so a change flipping either can
 *     change ``B``'s unset-required status.
 *   - ``readonly`` does not affect that scan, but is included as a safe
 *     over-approximation (per the perf-fix spec) — extra dependents only cost a
 *     redundant re-check, never a missed one.
 *
 * Non-field free variables are handled as follows (documented, deliberate):
 *   - ``parent`` / ``parent.*``: a reference to the parent record. It is NOT a
 *     field of this record, so it produces no same-record dependency here. The
 *     parent-triggered re-validation path covers it: on any parent commit the
 *     parent re-validates its (currently-invalid) x2many child lists, which
 *     recurse into the children — see the x2many handling in ``checkValidity``.
 *   - ``context`` / ``uid`` / ``allowed_company_ids`` / builtins: stable during
 *     field editing (set at view load), so they create no per-commit
 *     dependency.
 *   - Unparseable modifier ({@link UNKNOWN_DEPENDENCIES}): the field is added to
 *     ``always`` and re-validated on every commit (airtight fallback).
 *
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
                // Self-references and non-field names (parent/context/builtins)
                // never trigger a same-record re-check via this map.
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
 * Compute the set of fields whose unset-required status could change as a
 * result of committing ``changedFieldNames``: the changed fields themselves,
 * plus every field whose ``invisible`` / ``required`` / ``readonly`` modifier
 * references one of them, plus fields with an unparseable modifier (always
 * re-validated as a fallback).
 *
 * This is the scope passed to the ``removeInvalidOnly`` re-validation so it can
 * avoid re-scanning (and re-evaluating the modifier expressions of) fields that
 * provably cannot have changed status.
 *
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

// Changeset computation
// ---------------------------------------------------------------------------

/**
 * Compute the minimal changeset to send to the server from pending changes.
 *
 * This is the pure core of Record._getChanges (which delegates here — the two
 * used to be hand-inlined copies of the same algorithm). It determines which
 * fields have changed, skips readonly fields (unless forceSave), skips property
 * fields, and formats values for the server.
 *
 * For x2many fields, the caller must provide a `getCommands` callback that
 * retrieves the ORM command list from the StaticList datapoint.
 *
 * @param {Object} params
 * @param {Object} params.changes - pending field changes (Record._changes)
 * @param {Object} params.values - server-confirmed values (Record._values)
 * @param {boolean} params.isNew - whether the record has no resId
 * @param {Object} params.fields - field definitions
 * @param {Object} params.activeFields - active field metadata
 * @param {Object} params.evalContext - for evaluating readonly expressions
 * @param {Object} [params.options]
 * @param {boolean} [params.options.withReadonly] - include readonly fields
 * @param {(fieldName: string, value: any, withReadonly: boolean) => any[]} params.getCommands
 *     Callback to get ORM commands for x2many fields.
 * @returns {Object} changeset keyed by field name, values in server format
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

        // Skip the id pseudo-field
        if (fieldName === "id") {
            continue;
        }

        // Skip readonly fields unless explicitly requested or forceSave is set
        if (
            !withReadonly &&
            fieldName in activeFields &&
            isFieldReadonly(activeFields[fieldName], evalContext) &&
            !activeFields[fieldName].forceSave
        ) {
            continue;
        }

        // Skip computed property fields (handled by their parent)
        if (field.relatedPropertyField) {
            continue;
        }

        // x2many fields: delegate to command builder
        if (field.type === "one2many" || field.type === "many2many") {
            const commands = getCommands(fieldName, value, withReadonly);
            if (!isNew && !commands.length && !withReadonly) {
                continue;
            }
            result[fieldName] = commands;
        } else {
            result[fieldName] = formatServerValue(field.type, value);
        }
    }

    return result;
}
