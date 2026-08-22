// @ts-check
/** @odoo-module native */

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
    target.dispatchEvent(new InputEvent("input", { bubbles: true }));
}

function onFocus(/** @type {FocusEvent} */ ev) {
    /** @type {HTMLInputElement} */ (ev.target).select();
}

export function useNumpadDecimal() {
    const ref = useRef("numpadDecimal");
    const isIOSDevice = isIOS();
    const handleKeydown = (/** @type {KeyboardEvent} */ ev) => {
        if (/** @type {HTMLElement} */ (ev.target).closest("input")) {
            onKeydown(ev);
        }
    };
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
                inputs.forEach((/** @type {HTMLInputElement} */ input) =>
                    input.removeAttribute("inputmode"),
                );
            }
            return () => {
                el.removeEventListener("keydown", handleKeydown);
                el.removeEventListener("focusin", handleFocusin);
            };
        },
        () => [ref.el],
    );
}
