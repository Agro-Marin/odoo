// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/_behaviours/dropdown_group_hook */

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

    const group = {
        isInGroup: DROPDOWN_GROUP in env,
        get isOpen() {
            return (
                this.isInGroup &&
                [...envAny[DROPDOWN_GROUP]].some((dropdown) => dropdown.isOpen)
            );
        },
    };

    if (group.isInGroup) {
        const dropdown = /** @type {any} */ (useComponent());
        useEffect(
            () => {
                envAny[DROPDOWN_GROUP].add(dropdown.state);
                return () => envAny[DROPDOWN_GROUP].delete(dropdown.state);
            },
            () => [],
        );
    }

    return group;
}
