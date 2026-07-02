// @ts-check
/** @odoo-module native */

/** @module @web/fields/numpad_decimal_hook - OWL hook that replaces numpad decimal key with the locale decimal separator */

import { useEffect, useRef } from "@odoo/owl";
import { isIOS } from "@web/core/browser/feature_detection";
import { localization } from "@web/core/l10n/localization";
function onKeydown(/** @type {KeyboardEvent} */ ev) {
    const decimalPoint = localization.decimalPoint;
    const target = /** @type {HTMLInputElement} */ (ev.target);
    if (
        !([".", ","].includes(ev.key) && ev.code === "NumpadDecimal") ||
        ev.key === decimalPoint ||
        target.type === "number"
    ) {
        return;
    }
    ev.preventDefault();
    target.setRangeText(
        decimalPoint,
        /** @type {number} */ (target.selectionStart),
        /** @type {number} */ (target.selectionEnd),
        "end",
    );
}

function onFocus(/** @type {FocusEvent} */ ev) {
    /** @type {HTMLInputElement} */ (ev.target).select();
}

/**
 * This hook replaces the decimal separator of the numpad decimal key
 * by the decimal separator from the user's language setting when user
 * edits an input. The input is found using a t-ref="numpadDecimal"
 * reference in the current component. It can be placed directly on an
 * input or an element containing multiple inputs that require the
 * behavior
 *
 * NOTE: Special consideration for the input type = "number". In this
 * case, whatever the user types, we let the browser's default behavior.
 *
 * NOTE: On IOS devices, the inputmode attribute prevents the user from
 * entering a negative number (the minus sign is not on the virtual keyboard),
 * so we need to remove it.
 */
export function useNumpadDecimal() {
    const ref = useRef("numpadDecimal");
    const isIOSDevice = isIOS();
    // Delegated listeners: a single pair on the root element instead of one
    // pair per input rewired on every patch.
    const handleKeydown = (/** @type {KeyboardEvent} */ ev) => {
        if (/** @type {HTMLElement} */ (ev.target).closest("input")) {
            onKeydown(ev);
        }
    };
    // "focus" does not bubble: use "focusin" for delegation.
    const handleFocusin = (/** @type {FocusEvent} */ ev) => {
        if (/** @type {HTMLElement} */ (ev.target).closest("input")) {
            onFocus(ev);
        }
    };
    useEffect(
        (el) => {
            if (!el) {
                return;
            }
            el.addEventListener("keydown", handleKeydown);
            el.addEventListener("focusin", handleFocusin);
            if (isIOSDevice) {
                const inputs =
                    el.nodeName === "INPUT" ? [el] : el.querySelectorAll("input");
                inputs.forEach((input) => input.removeAttribute("inputmode"));
            }
            return () => {
                el.removeEventListener("keydown", handleKeydown);
                el.removeEventListener("focusin", handleFocusin);
            };
        },
        () => [ref.el],
    );
}
