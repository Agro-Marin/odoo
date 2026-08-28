/** @odoo-module native */
import { EventBus, whenReady } from "@odoo/owl";
import { isBrowserChrome, isMobileOS } from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

// Modifier keydowns carry no barcode content. They are dropped here rather than
// scrubbed out of the assembled string afterwards: once 'Alt' is in the buffer
// it is indistinguishable from a barcode that genuinely spells "Alt", and
// removing it corrupts the scan (e.g. "ShiftKnob" -> "Knob").
const MODIFIER_KEYS = new Set(["Alt", "AltGraph", "Control", "Meta", "Shift"]);

// Shorter inputs are treated as stray typing rather than a scan.
const MIN_BARCODE_LENGTH = 3;

function isEditable(element) {
    return element.matches('input,textarea,[contenteditable="true"]');
}

function makeBarcodeInput() {
    const inputEl = document.createElement("input");
    inputEl.setAttribute(
        "style",
        "position:fixed;top:50%;transform:translateY(-50%);z-index:-1;opacity:0",
    );
    inputEl.setAttribute("autocomplete", "off");
    inputEl.setAttribute("inputmode", "none"); // magic! prevent native keyboard from popping
    inputEl.classList.add("o-barcode-input");
    inputEl.setAttribute("name", "barcode");
    return inputEl;
}

export const barcodeService = {
    // Keys from a barcode scanner are usually processed as quick as possible,
    // but some scanners can use an intercharacter delay (we support <= 150 ms).
    // `??`, not `||`: a configured 0 is a value, not an absent one.
    maxTimeBetweenKeysInMs: session.max_time_between_keys_in_ms ?? 150,

    // this is done here to make it easily mockable in mobile tests
    isMobileChrome: isMobileOS() && isBrowserChrome(),

    /**
     * Normalize a raw scan before it is dispatched.
     *
     * The base implementation passes the barcode through: modifier keys never
     * reach the buffer, so there is nothing to strip. It stays as the hook
     * where a nomenclature re-encodes scanner-specific sequences --
     * `barcodes_gs1_nomenclature` patches it to map group separators to FNC1.
     *
     * @param {string} barcode
     * @returns {string}
     */
    cleanBarcode: function (barcode) {
        return barcode;
    },

    start() {
        const bus = new EventBus();
        let timeout = null;

        let bufferedBarcode = "";
        let currentTarget = null;
        let barcodeInput = null;

        function handleBarcode(barcode, target) {
            bus.trigger("barcode_scanned", { barcode, target });
            if (target && target.getAttribute("barcode_events") === "true") {
                const barcodeScannedEvent = new CustomEvent("barcode_scanned", {
                    detail: { barcode, target },
                });
                target.dispatchEvent(barcodeScannedEvent);
            }
        }

        /**
         * check if we have a barcode, and trigger appropriate events
         */
        function checkBarcode(ev) {
            let str = barcodeInput ? barcodeInput.value : bufferedBarcode;
            str = barcodeService.cleanBarcode(str);
            if (str.length >= MIN_BARCODE_LENGTH) {
                if (ev) {
                    ev.preventDefault();
                }
                handleBarcode(str, currentTarget);
            }
            if (barcodeInput) {
                barcodeInput.value = "";
            }
            bufferedBarcode = "";
            currentTarget = null;
        }

        function keydownHandler(ev) {
            if (!ev.key) {
                // Chrome may trigger incomplete keydown events under certain circumstances.
                // E.g. when using browser built-in autocomplete on an input.
                // See https://stackoverflow.com/questions/59534586/google-chrome-fires-keydown-event-when-form-autocomplete
                return;
            }
            // Ignore 'Escape', 'Backspace', 'Insert', 'Delete', 'Home', 'End', Arrow*, F*, Page*, ...
            // meta is often used for UX purpose (like shortcuts)
            // Note: altKey/ctrlKey are not ignored because they can be used in
            // some barcodes (e.g. GS1 separator); it is only the modifier
            // keydowns themselves that carry nothing.
            const isModifier = MODIFIER_KEYS.has(ev.key);
            const isSpecialKey = !isModifier && (ev.key.length > 1 || ev.metaKey);
            const isEndCharacter = ev.key === "Enter" || ev.key === "Tab";

            // Don't catch non-printable keys except 'enter' and 'tab'
            if (isSpecialKey && !isEndCharacter) {
                return;
            }

            const target = ev.target;
            // Don't catch events targeting elements that are editable because we
            // have no way of redispatching 'genuine' key events. Resent events
            // don't trigger native event handlers of elements. So this means that
            // our fake events will not appear in eg. an <input> element.
            //
            // `currentTarget` is only committed once this guard has decided the
            // keydown belongs to a scan: an ordinary keystroke that lands here
            // and returns early must not overwrite the target of a scan whose
            // debounce timer is still pending.
            if (
                target !== barcodeInput &&
                isEditable(target) &&
                !target.dataset.enableBarcode &&
                target.getAttribute("barcode_events") !== "true"
            ) {
                return;
            }
            currentTarget = target;

            clearTimeout(timeout);
            if (isEndCharacter) {
                checkBarcode(ev);
            } else {
                // A modifier keeps the sequence alive without contributing to it.
                if (!isModifier) {
                    bufferedBarcode += ev.key;
                }
                timeout = setTimeout(
                    checkBarcode,
                    barcodeService.maxTimeBetweenKeysInMs,
                );
            }
        }

        function mobileChromeHandler(ev) {
            if (ev.key === "Unidentified") {
                return;
            }
            if (
                document.activeElement &&
                !document.activeElement.matches(
                    'input:not([type]), input[type="text"], textarea, [contenteditable], ' +
                        '[type="email"], [type="number"], [type="password"], [type="tel"], [type="search"]',
                )
            ) {
                barcodeInput.focus();
            }
            keydownHandler(ev);
        }

        whenReady(() => {
            const isMobileChrome = barcodeService.isMobileChrome;
            if (isMobileChrome) {
                barcodeInput = makeBarcodeInput();
                document.body.appendChild(barcodeInput);
            }
            const handler = isMobileChrome ? mobileChromeHandler : keydownHandler;
            document.body.addEventListener("keydown", handler);
        });

        return {
            bus,
            /**
             * Dispatch a barcode as if it had been scanned.
             *
             * Lets callers and tests inject a scan without synthesising a
             * keydown sequence, which is the only reason every barcode test
             * carries its own `simulateBarCode` helper.
             *
             * @param {string} barcode
             * @param {EventTarget} [target]
             */
            scan(barcode, target = document.body) {
                handleBarcode(barcodeService.cleanBarcode(barcode), target);
            },
        };
    },
};

registry.category("services").add("barcode", barcodeService);
