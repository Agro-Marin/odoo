// @ts-check
/** @odoo-module native */

import { onWillRender, useComponent } from "@odoo/owl";
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
 * One parsed `Domain` per distinct action expression, so a re-evaluation on
 * every prop update does not re-parse. Per hook instance rather than
 * module-wide: the set of expressions a widget sees is its arch's, and a
 * module-level map keyed on every expression ever met was never pruned.
 *
 * @returns {(action: any) => Domain | null}
 */
function makeDomainResolver() {
    /** @type {Map<string, Domain>} */
    const cache = new Map();
    return (action) => {
        if (!action) {
            return null;
        }
        const key = typeof action === "string" ? action : JSON.stringify(action);
        let domain = cache.get(key);
        if (!domain) {
            domain = new Domain(action);
            cache.set(key, domain);
        }
        return domain;
    };
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
    const domainFor = makeDomainResolver();

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

    const component = useComponent();
    const activeActions = compute(component.props);
    // Before every render, not only on a props change: the domains read the
    // record's evalContext, and an edit of the record re-renders the widget
    // without changing its props.
    onWillRender(() => {
        Object.assign(activeActions, compute(component.props));
    });

    return activeActions;
}
