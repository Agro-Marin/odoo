// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/relational_active_actions - Reactive OWL hook for computing x2many field CRUD permissions */

import { onWillUpdateProps, useComponent } from "@odoo/owl";
import { Domain } from "@web/core/domain";

/**
 * @typedef {Object} RelationalActiveActions {
 * @property {"x2m"} type
 * @property {boolean} create
 * @property {boolean} createEdit
 * @property {boolean} delete
 * @property {boolean} [link]
 * @property {boolean} [unlink]
 * @property {boolean} [write]
 * @property {Function | null} onDelete
 */

const STANDARD_ACTIVE_ACTIONS = [
    "create",
    "createEdit",
    "delete",
    "link",
    "unlink",
    "write",
];

/**
 * The per-props inputs a caller's ``getEvalParams`` supplies to one
 * recomputation of the active actions.
 *
 * Every member is optional, and that is the point: the default
 * ``getEvalParams`` returns ``{}``, and ``compute`` supplies its own fallbacks
 * (``evalContext = {}``, ``readonly = true``, and ``edit ?? crudOptions.edit``
 * for callers that still pass ``edit`` through ``crudOptions``). Naming the
 * shape here replaces two implicit contracts that disagreed: ``getEvalParams``
 * was declared to return an untyped ``Record<any, any>``, while ``compute``'s
 * parameter type was inferred from its destructuring pattern — which made
 * ``edit`` REQUIRED, since it alone has no default in the pattern. The two were
 * therefore mutually unassignable even though the runtime contract is exactly
 * "any subset of these three".
 *
 * @typedef {Object} ActiveActionsEvalParams
 * @property {Object} [evalContext] context the CRUD domains are evaluated against
 * @property {boolean} [readonly] whether the field is currently readonly
 * @property {boolean} [edit] per-props edit permission; falls back to
 *   ``crudOptions.edit``
 */

/**
 * Reactive OWL hook for x2m field CRUD permissions. Complements the static
 * `getActiveActions()` in `@web/views/view_utils` which parses view-level XML attributes.
 * The two are intentionally separate: view-level actions are parsed once at arch parse
 * time, while field-level actions are evaluated reactively against domain expressions
 * and fed through `subViewActiveActions`.
 *
 * @param {Object} params
 * @param {string} params.fieldType
 * @param {Record<string, boolean>} [params.subViewActiveActions={}]
 * @param {Object} [params.crudOptions={}]
 * @param {(props: Record<string, any>) => ActiveActionsEvalParams} [params.getEvalParams=() => ({})]
 * @returns {RelationalActiveActions}
 */
export function useActiveActions({
    fieldType,
    subViewActiveActions = {},
    crudOptions = {},
    getEvalParams = () => ({}),
}) {
    /** @param {ActiveActionsEvalParams} evalParams */
    const compute = ({ evalContext = {}, readonly = true, edit }) => {
        const result = /** @type {RelationalActiveActions} */ ({
            type: /** @type {any} */ (fieldType),
            onDelete: null,
        });
        const evalAction = (actionName) => evals[actionName](evalContext);

        result.create = !readonly && evalAction("create");
        result.createEdit = !readonly && result.create && crudOptions.createEdit;
        /** @type {any} */ (result).edit = edit ?? crudOptions.edit;
        result.delete = !readonly && evalAction("delete");
        result.write = (isMany2Many || !readonly) && evalAction("write");

        if (isMany2Many) {
            result.link = !readonly && evalAction("link");
            result.unlink = !readonly && evalAction("unlink");
        }

        if (result.unlink || (!isMany2Many && result.delete)) {
            result.onDelete = crudOptions.onDelete;
        }

        return result;
    };

    const props = useComponent().props;
    const isMany2Many = fieldType === "many2many";

    const evals = {};
    for (const actionName of STANDARD_ACTIVE_ACTIONS) {
        /** @type {(evalContext?: any) => boolean} */
        let evalFn = () => true;
        if (crudOptions[actionName] != null) {
            const action = crudOptions[actionName];
            let domain;
            evalFn = (evalContext) => {
                domain ??= action ? new Domain(action) : null;
                return Boolean(domain && domain.contains(evalContext));
            };
        }

        if (actionName in subViewActiveActions) {
            const viewActiveAction = subViewActiveActions[actionName];
            evals[actionName] = (evalContext) =>
                viewActiveAction && evalFn(evalContext);
        } else {
            evals[actionName] = evalFn;
        }
    }

    const activeActions = compute(getEvalParams(props));
    onWillUpdateProps(
        /** @type {any} */ (
            (nextProps) => {
                Object.assign(activeActions, compute(getEvalParams(nextProps)));
            }
        ),
    );

    return activeActions;
}
