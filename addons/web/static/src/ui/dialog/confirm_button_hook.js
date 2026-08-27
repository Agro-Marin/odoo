// @ts-check
/** @odoo-module native */

import { useRef } from "@odoo/owl";

/**
 * @param {string} [refName]
 * @returns {(disabled: boolean) => void}
 */
export function useConfirmButton(refName = "confirm") {
    const buttonRef = useRef(refName);
    return (disabled) => {
        const el = /** @type {HTMLButtonElement | null} */ (buttonRef.el);
        if (el) {
            el.disabled = disabled;
        }
    };
}
