// @ts-check
/** @odoo-module native */

import { useRef } from "@odoo/owl";

/**
 * A dialog's confirm button, for the dialogs that validate before they accept.
 *
 * Two of them do - the domain selector asks the server whether the domain runs,
 * the expression editor evaluates locally - and both have to stop a second
 * confirm from landing while the first is still being judged, then hand the
 * button back if the answer is no.
 *
 * The write is guarded rather than asserted: by the time an await resolves the
 * button is gone if the dialog was closed under it.
 *
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
