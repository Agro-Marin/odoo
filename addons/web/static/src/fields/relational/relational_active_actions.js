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
 * @param {(props: Record<string, any>) => Record<any, any>} [params.getEvalParams=() => ({})]
 * @returns {RelationalActiveActions}
 */
export function useActiveActions({
    fieldType,
    subViewActiveActions = {},
    crudOptions = {},
    getEvalParams = () => ({}),
}) {
    const compute = ({ evalContext = {}, readonly = true, edit }) => {
        const result = /** @type {RelationalActiveActions} */ ({
            type: /** @type {any} */ (fieldType),
            onDelete: null,
        });
        const evalAction = (actionName) => evals[actionName](evalContext);

        result.create = !readonly && evalAction("create");
        result.createEdit = !readonly && result.create && crudOptions.createEdit; // always a boolean
        // `edit` is now sourced per-props from getEvalParams (like readonly) so a
        // record whose edition state changes after mount re-derives it, instead
        // of keeping the setup-time snapshot. Fall back to crudOptions.edit for
        // callers that still pass it there (e.g. enterprise/stock_move).
        /** @type {any} */ (result).edit = edit ?? crudOptions.edit; // always a boolean
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
            // Lazy: some crudOptions entries are plain booleans whose eval
            // function is never invoked (e.g. createEdit); only build the
            // Domain once, on first evaluation.
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
