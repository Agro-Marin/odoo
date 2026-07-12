// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_utils - Pure utility functions for field attribute evaluation (invisible, readonly, required) */

/**
 * Pure utility functions extracted from Record — no OWL reactivity dependency,
 * so they're testable with plain assert in <1ms.
 *
 * @see record_value_transforms.js for value formatting and context building
 * @see record_validator.js for field validation logic
 */

import { evaluateBooleanExpr, getExprFreeVariables } from "@web/core/py_js/py";

import { formatServerValue } from "./record_value_transforms.js";

// Field attribute evaluation

/**
 * Evaluate a field attribute expression (invisible, readonly, required).
 * Pure core of Record._isInvisible, _isReadonly, _isRequired.
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

// Modifier dependency analysis (scoped per-commit re-validation)

/**
 * Sentinel returned by {@link extractFieldNamesFromExpr} when the expression
 * cannot be statically analysed (parse failure). Callers must treat it as
 * "depends on everything" and fall back to unconditional re-validation.
 * @type {null}
 */
const UNKNOWN_DEPENDENCIES = null;

/**
 * Extract the field-name root identifiers referenced by a modifier expression
 * (``invisible`` / ``required`` / ``readonly``). Thin wrapper around
 * {@link getExprFreeVariables}: also returns non-field names (``parent``,
 * ``context``, ``uid``, builtins) — the caller filters those against the real
 * field universe. Returns {@link UNKNOWN_DEPENDENCIES}
 * (``null``) when the expression is falsy or fails to parse, signalling the
 * field must be re-validated on every commit (airtight fallback).
 *
 * @param {string|false|undefined} expr
 * @returns {Set<string>|null} free-variable root names, or ``null`` if unknown
 */
export function extractFieldNamesFromExpr(expr) {
    if (!expr || typeof expr !== "string") {
        // No modifier (or a boolean literal already normalised away).
        return new Set();
    }
    if (expr === "True" || expr === "False" || expr === "1" || expr === "0") {
        return new Set();
    }
    try {
        return getExprFreeVariables(expr);
    } catch {
        // Unparseable — cannot prove independence, so caller always re-validates.
        return UNKNOWN_DEPENDENCIES;
    }
}

/**
 * Per-``activeFields`` cache of the modifier-dependency inverse map, keyed on
 * the (arch-stable) ``activeFields`` object so extraction runs once per view.
 * ``WeakMap`` lets the entry be collected when the view is torn down.
 *
 * @type {WeakMap<object, { dependents: Map<string, Set<string>>, always: Set<string> }>}
 */
const _modifierDependencyCache = new WeakMap();

/**
 * Build (and memoise) the inverse dependency map for a view's ``activeFields``:
 * for each field ``X``, the fields ``B`` whose ``invisible``/``required``/
 * ``readonly`` modifier references ``X``. ``readonly`` doesn't itself drive
 * {@link findUnsetRequiredFields} but is included as a safe over-approximation
 * (extra dependents only cost a redundant re-check, never a missed one).
 *
 * ``parent``/``context``/``uid``/builtins are non-field free variables and
 * create no same-record dependency here — parent changes are covered by the
 * parent-triggered re-validation path (see x2many handling in
 * ``checkValidity``). An unparseable modifier ({@link UNKNOWN_DEPENDENCIES})
 * adds the field to ``always``, re-validated on every commit as a fallback.
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
                // Self-refs and non-field names never trigger a re-check here.
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
 * Compute the set of fields whose unset-required status could change from
 * committing ``changedFieldNames``: the changed fields, every field whose
 * modifier references one of them, plus fields with an unparseable modifier.
 * Passed as scope to the ``removeInvalidOnly`` re-validation so it can skip
 * fields that provably cannot have changed status.
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

/**
 * Compute the minimal changeset to send to the server from pending changes.
 * Pure core of Record._getChanges. Skips readonly fields (unless forceSave)
 * and property fields; formats values for the server. For x2many fields, the
 * caller provides `getCommands` to retrieve ORM commands from the StaticList.
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
            // Defensive (urgent/tab-close path): x2many preprocessing may not
            // have run, so ``value`` can still be the RAW command array the
            // field dispatched (``[[0, 0, {...}]]``) instead of the StaticList
            // ``_applyCommands`` installs. A raw array has no ``_getCommands``,
            // so ``getCommands`` would throw a TypeError and abort the WHOLE
            // save — on the sendBeacon path that means the beacon never fires
            // and every pending field is silently lost. Treat a non-StaticList
            // as "no commands": best-effort drop of this one x2many edit so
            // every serializable field still reaches the server. On the normal
            // path ``value`` is always a StaticList, so this never trips.
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
            // Defensive (urgent/tab-close path): a many2one still awaiting its
            // ``name_create`` is a truthy ``{display_name}`` with no numeric id,
            // which ``formatServerValue`` maps to ``undefined``. Emitting it
            // would place an ``undefined`` on the payload that ``JSON.stringify``
            // silently drops — the field is lost either way, but keeping it here
            // lets it masquerade as a real write. Drop it explicitly so the
            // changeset never carries an ``undefined`` and every OTHER field
            // still saves. On the normal path m2o values always carry an id, so
            // ``serverValue`` is never ``undefined`` here.
            if (serverValue === undefined) {
                continue;
            }
            result[fieldName] = serverValue;
        }
    }

    return result;
}
