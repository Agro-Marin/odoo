// @ts-check
/** @odoo-module native */

import { onWillUpdateProps, useComponent } from "@odoo/owl";
import { Domain } from "@web/core/domain";

/**
 * @typedef {Object} RelationalActiveActions
 * @property {"x2m"} type
 * @property {boolean} create
 * @property {boolean | undefined} createEdit
 * @property {boolean} delete
 * @property {boolean | undefined} edit
 * @property {boolean} [link]
 * @property {boolean} [unlink]
 * @property {boolean} [write]
 * @property {Function | null} onDelete
 */

/**
 * @typedef {Object} ActiveActionsEvalParams
 * @property {Object} [evalContext]
 * @property {boolean} [readonly]
 * @property {boolean} [edit]
 */

/**
 * @type {Map<string, Domain | null>}
 */
const domainCache = new Map();

/**
 * @param {any} action
 * @returns {Domain | null}
 */
function domainFor(action) {
    if (!action) {
        return null;
    }
    const key = typeof action === "string" ? action : JSON.stringify(action);
    if (!domainCache.has(key)) {
        domainCache.set(key, new Domain(action));
    }
    return /** @type {Domain | null} */ (domainCache.get(key));
}

/**
 * @param {Object} params
 * @param {string} params.fieldType
 * @param {Record<string, boolean>} [params.subViewActiveActions={}]
 * @param {Object | ((props: Record<string, any>) => Object)} [params.crudOptions={}]
 * @param {(props: Record<string, any>) => ActiveActionsEvalParams} [params.getEvalParams=() => ({})]
 * @returns {RelationalActiveActions}
 */
export function useActiveActions({
    fieldType,
    subViewActiveActions = {},
    crudOptions = {},
    getEvalParams = () => ({}),
}) {
    const isMany2Many = fieldType === "many2many";

    /**
     * @param {Object} options
     * @param {string} actionName
     * @param {Object} evalContext
     * @returns {boolean}
     */
    const evalAction = (options, actionName, evalContext) => {
        let allowed = true;
        if (options[actionName] != null) {
            const domain = domainFor(options[actionName]);
            allowed = Boolean(domain && domain.contains(evalContext));
        }
        if (actionName in subViewActiveActions) {
            allowed = Boolean(subViewActiveActions[actionName]) && allowed;
        }
        return allowed;
    };

    /**
     * @param {Record<string, any>} props
     * @returns {RelationalActiveActions}
     */
    const compute = (props) => {
        const { evalContext = {}, readonly = true, edit } = getEvalParams(props);
        const options =
            typeof crudOptions === "function" ? crudOptions(props) : crudOptions;
        const result = /** @type {RelationalActiveActions} */ ({
            type: /** @type {any} */ (fieldType),
            onDelete: null,
        });
        const evaluate = (actionName) => evalAction(options, actionName, evalContext);

        result.create = !readonly && evaluate("create");
        result.createEdit = !readonly && result.create && options.createEdit;
        result.edit = edit ?? options.edit;
        result.delete = !readonly && evaluate("delete");
        result.write = (isMany2Many || !readonly) && evaluate("write");

        if (isMany2Many) {
            result.link = !readonly && evaluate("link");
            result.unlink = !readonly && evaluate("unlink");
        }

        if (result.unlink || (!isMany2Many && result.delete)) {
            result.onDelete = options.onDelete;
        }

        return result;
    };

    const activeActions = compute(useComponent().props);
    onWillUpdateProps(
        /** @type {any} */ (
            (nextProps) => {
                Object.assign(activeActions, compute(nextProps));
            }
        ),
    );

    return activeActions;
}
