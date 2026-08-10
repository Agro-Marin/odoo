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
    if (!pager) {
        return;
    }
    // Read the two spans rather than slicing the pager's rendered text. The
    // old form asked `innerText.includes("-")` whether this was a multi-record
    // view and `innerText.split("/")[0]` for the position, which conflates the
    // value with the limit and breaks on any change to the pager's markup or
    // separator. `.o_pager_limit` was also dereferenced without a null check.
    const valueEl = pager.querySelector(".o_pager_value");
    const limitEl = pager.querySelector(".o_pager_limit");
    if (!valueEl || !limitEl) {
        return;
    }
    // A multi-record view shows a span such as "1-80"; there is no single
    // record to page to, so the command does not apply.
    const value = valueEl.textContent.trim();
    if (value.includes("-")) {
        return;
    }
    const current = parseInt(value, 10);
    const limit = parseInt(limitEl.textContent.trim(), 10);
    if (!Number.isInteger(current) || !Number.isInteger(limit)) {
        return;
    }
    const next = position === "first" ? 1 : limit;
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
