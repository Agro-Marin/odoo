// @ts-check
/** @odoo-module native */

import { getDomainDisplayedOperators } from "@web/components/domain_selector/domain_selector_operator_editor";
import { getDefaultValue } from "@web/components/tree_editor";
import { condition } from "@web/core/tree/condition_tree";
import { domainFromTree } from "@web/core/tree/domain_from_tree";
import { getDefaultPath } from "@web/core/tree/utils";
import { useService } from "@web/core/utils/hooks";
/**
 * @param {Record<string, Record<string, any>>} fieldDefs
 * @returns {import("@web/core/tree/condition_tree").Condition}
 */
export function getDefaultCondition(fieldDefs) {
    const defaultPath = getDefaultPath(fieldDefs);
    const fieldDef = fieldDefs[defaultPath];
    const operator = getDomainDisplayedOperators(fieldDef)[0];
    const value = getDefaultValue(fieldDef, operator);
    return condition(fieldDef.name, operator, value);
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
