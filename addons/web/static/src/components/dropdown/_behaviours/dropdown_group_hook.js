// @ts-check
/** @odoo-module native */

import { useEffect } from "@odoo/owl";
import { useDropdownGroupMembership } from "@web/components/dropdown/dropdown_group";

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
    const membership = useDropdownGroupMembership();
    const group = {
        isInGroup: Boolean(membership),
        get isOpen() {
            return this.isInGroup && Boolean(membership?.isOpen);
        },
    };

    if (group.isInGroup) {
        useEffect(
            () => {
                membership?.add(dropdownState);
                return () => membership?.delete(dropdownState);
            },
            () => [],
        );
    }

    return group;
}
