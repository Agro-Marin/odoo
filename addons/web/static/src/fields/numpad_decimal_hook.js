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
    // setRangeText does not fire an input event, so useInputField's dirty
    // tracking (FIELD_IS_DIRTY, field validity reset) would miss this
    // keystroke without a synthetic one.
    target.dispatchEvent(new InputEvent("input", { bubbles: true }));
}

function onFocus(/** @type {FocusEvent} */ ev) {
    /** @type {HTMLInputElement} */ (ev.target).select();
}

/**
 * Replace the numpad decimal key's separator with the locale's decimal
 * separator on inputs under a t-ref="numpadDecimal" ref (single input or
 * a container of several).
 *
 * NOTE: input type="number" is left to the browser's default behavior.
 * NOTE: on iOS, the inputmode attribute hides the minus sign on the virtual
 * keyboard, so it is removed to allow negative numbers.
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
