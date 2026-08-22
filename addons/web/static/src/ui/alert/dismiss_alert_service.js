// @ts-check
/** @odoo-module native */

import { whenReady } from "@odoo/owl";
import { registry } from "@web/core/registry";

const dismissAlertService = {
    start() {
        /** @param {MouseEvent} ev */
        const onClick = (ev) => {
            const target = /** @type {Element} */ (ev.target);
            const trigger = target?.closest?.("[data-dismiss-alert]");
            if (!trigger) {
                return;
            }
            ev.preventDefault();
            trigger.closest(".alert")?.remove();
        };

        let destroyed = false;
        whenReady(() => {
            if (!destroyed) {
                document.body.addEventListener("click", onClick);
            }
        });

        return {
            destroy() {
                destroyed = true;
                document.body.removeEventListener("click", onClick);
            },
        };
    },
};

registry.category("services").add("dismiss_alert", dismissAlertService);
