// @ts-check
/** @odoo-module native */

import { useComponent, useEffect, useEnv } from "@odoo/owl";
import { DROPDOWN_GROUP } from "@web/components/dropdown/dropdown_group";

/**
 * @typedef DropdownGroupState
 * @property {boolean} isInGroup
 * @property {boolean} isOpen
 */

/**
 * @returns {DropdownGroupState}
 */
export function useDropdownGroup() {
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
        const dropdown = /** @type {any} */ (useComponent());
        useEffect(
            () => {
                membership.add(dropdown.state);
                return () => membership.delete(dropdown.state);
            },
            () => [],
        );
    }

    return group;
}
