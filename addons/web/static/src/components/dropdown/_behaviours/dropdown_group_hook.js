// @ts-check
/** @odoo-module native */

import { useDropdownGroupMembership } from "@web/components/dropdown/dropdown_group";
import { useLayoutEffect } from "@web/core/utils/layout_effect";

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
        useLayoutEffect(
            () => {
                membership?.add(dropdownState);
                return () => membership?.delete(dropdownState);
            },
            () => [],
        );
    }

    return group;
}
