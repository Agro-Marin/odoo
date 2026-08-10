/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { getVisibleElements } from "@web/core/utils/dom/ui";
import { Macro } from "@web/core/utils/macro";

const ACTION_HELPERS = {
    click(el) {
        el.dispatchEvent(new MouseEvent("mouseover"));
        el.dispatchEvent(new MouseEvent("mouseenter"));
        el.dispatchEvent(new MouseEvent("mousedown"));
        el.dispatchEvent(new MouseEvent("mouseup"));
        el.click();
        el.dispatchEvent(new MouseEvent("mouseout"));
        el.dispatchEvent(new MouseEvent("mouseleave"));
    },
    text(el, value) {
        this.click(el);
        el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true }));
        el.dispatchEvent(new InputEvent("change", { bubbles: true }));
    },
};

function clickOnButton(selector) {
    const button = document.body.querySelector(selector);
    if (button) {
        button.click();
    }
}
function updatePager(position) {
    const pager = document.body.querySelector("nav.o_pager");
    if (!pager || pager.innerText.includes("-")) {
        // we don't change pages if we are in a multi record view
        return;
    }
    let next;
    if (position === "first") {
        next = 1;
    } else {
        next = parseInt(pager.querySelector(".o_pager_limit").textContent, 10);
    }
    const current = parseInt(pager.innerText.split("/")[0], 10);
    if (current === next) {
        return;
    }
    new Macro({
        name: "updating pager",
        timeout: 1000,
        steps: [
            {
                trigger: "span.o_pager_value",
                async action(trigger) {
                    ACTION_HELPERS.click(trigger);
                },
            },
            {
                trigger: "input.o_pager_value",
                async action(trigger) {
                    ACTION_HELPERS.text(trigger, next);
                },
            },
        ],
    }).start();
}

export const COMMANDS = {
    // There is no OCDEDIT: the form view has had no explicit edit mode since
    // Odoo 17, so `.o_form_button_edit` no longer exists anywhere. Keeping the
    // key mapped to a selector that matches nothing made the scan a silent
    // no-op; unmapped, it now reports "Unknown barcode command".
    OCDDISC: () => clickOnButton(".o_form_button_cancel"),
    OCDSAVE: () => clickOnButton(".o_form_button_save"),
    OCDPREV: () => clickOnButton(".o_pager_previous"),
    OCDNEXT: () => clickOnButton(".o_pager_next"),
    OCDPAGERFIRST: () => updatePager("first"),
    OCDPAGERLAST: () => updatePager("last"),
};

export const barcodeGenericHandlers = {
    dependencies: ["ui", "barcode", "notification"],
    start(env, { ui, barcode, notification }) {
        barcode.bus.addEventListener("barcode_scanned", (ev) => {
            const barcode = ev.detail.barcode;
            if (barcode.startsWith("OBT")) {
                // A barcode is untrusted input, so its text is escaped rather
                // than interpolated: `OBTa], [class` would otherwise build the
                // selector `[barcode_trigger=a], [class]` and click every
                // visible element on the page. A try/catch is not enough --
                // that payload is a *valid* selector, just not the intended one.
                const trigger = `[barcode_trigger=${CSS.escape(barcode.slice(3))}]`;
                // Only the first match is activated: a trigger is one command,
                // and clicking every match compounds a mis-scan.
                const [target] = getVisibleElements(ui.activeElement, trigger);
                if (target) {
                    target.click();
                }
            }
            if (barcode.startsWith("OCD")) {
                const fn = COMMANDS[barcode];
                if (fn) {
                    fn();
                } else {
                    notification.add(_t("Barcode: %(barcode)s", { barcode }), {
                        title: _t("Unknown barcode command"),
                        type: "danger",
                    });
                }
            }
        });
    },
};

registry.category("services").add("barcode_handlers", barcodeGenericHandlers);
