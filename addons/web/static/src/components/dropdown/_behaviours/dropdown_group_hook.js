// @ts-check
/** @odoo-module native */

import { useEffect, useEnv } from "@odoo/owl";
import { DROPDOWN_GROUP } from "@web/components/dropdown/dropdown_group";

/**
 * @typedef DropdownGroupState
 * @property {boolean} isInGroup
 * @property {boolean} isOpen
 */

/**
 * @param {Record<string, any>} dropdownState
 * @returns {DropdownGroupState}
 */
export function useDropdownGroup(dropdownState) {
    const env = useEnv();
    const /** @type {any} */ envAny = env;

    const membership = envAny[DROPDOWN_GROUP];
    const group = {
        isInGroup: DROPDOWN_GROUP in env,
        get isOpen() {
            return this.isInGroup && membership.isOpen;
        },
    };

    if (group.isInGroup) {
        useEffect(
            () => {
                membership.add(dropdownState);
                return () => membership.delete(dropdownState);
            },
            () => [],
        );
    }

    return group;
}
