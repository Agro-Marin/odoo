// @ts-check
/** @odoo-module native */

import { getDomainDisplayedOperators } from "@web/components/domain_selector/domain_selector_operator_editor";
import { getDefaultValue } from "@web/components/tree_editor";
import { condition } from "@web/core/tree/condition_tree";
import { domainFromTree } from "@web/core/tree/domain_from_tree";
import { getDefaultPath } from "@web/core/tree/utils";
import { useService } from "@web/core/utils/hooks";

/**
 * The condition an editor starts a new leaf from: the first field the model
 * offers, its first legal operator, and whatever that operator defaults to.
 *
 * The operator list is the parameter because it is the only thing the two
 * editors disagree about - the expression editor accepts a subset of what a
 * domain does.
 *
 * @param {Record<string, Record<string, any>>} fieldDefs
 * @param {(fieldDef: Record<string, any>) => string[]} getOperators
 * @returns {import("@web/core/tree/condition_tree").Condition}
 */
export function makeDefaultCondition(fieldDefs, getOperators) {
    const defaultPath = getDefaultPath(fieldDefs);
    const fieldDef = fieldDefs[defaultPath];
    const operator = getOperators(fieldDef)[0];
    const value = getDefaultValue(fieldDef, operator);
    return condition(fieldDef.name, operator, value);
}

/**
 * @param {Record<string, Record<string, any>>} fieldDefs
 * @returns {import("@web/core/tree/condition_tree").Condition}
 */
export function getDefaultCondition(fieldDefs) {
    return makeDefaultCondition(fieldDefs, getDomainDisplayedOperators);
}

/**
 * @param {Record<string, Record<string, any>>} fieldDefs
 * @returns {string}
 */
export function getDefaultDomain(fieldDefs) {
    return domainFromTree(getDefaultCondition(fieldDefs));
}

/**
 * @returns {(resModel: string) => Promise<string>}
 */
export function useGetDefaultLeafDomain() {
    const fieldService = useService("field");
    return async (resModel) => {
        const fieldDefs = await fieldService.loadFields(resModel);
        return getDefaultDomain(fieldDefs);
    };
}
