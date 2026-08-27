// @ts-check
/** @odoo-module native */

import { whenReady } from "@odoo/owl";
import { registry } from "@web/core/registry";

class DismissAlertService {
    constructor() {
        this.destroyed = false;
        // Bound through the instance rather than registered directly, so a
        // patch on onClick reaches the listener too (ADR-0021).
        this.listener = (/** @type {MouseEvent} */ ev) => this.onClick(ev);
        whenReady(() => {
            if (!this.destroyed) {
                document.body.addEventListener("click", this.listener);
            }
        });
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        const target = /** @type {Element} */ (ev.target);
        const trigger = target?.closest?.("[data-dismiss-alert]");
        if (!trigger) {
            return;
        }
        ev.preventDefault();
        trigger.closest(".alert")?.remove();
    }

    destroy() {
        this.destroyed = true;
        document.body.removeEventListener("click", this.listener);
    }
}

const dismissAlertService = {
    /** @returns {DismissAlertService} */
    start() {
        return new DismissAlertService();
    },
};

registry.category("services").add("dismiss_alert", dismissAlertService);
