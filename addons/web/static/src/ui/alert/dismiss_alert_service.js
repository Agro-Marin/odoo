// @ts-check
/** @odoo-module native */

/** @module @web/ui/alert/dismiss_alert_service - Click-to-dismiss for alerts declared in view arch */

import { whenReady } from "@odoo/owl";
import { registry } from "@web/core/registry";

/**
 * Dismissal for alerts written in view arch, replacing Bootstrap's
 * `data-bs-dismiss="alert"`.
 *
 * Arch is compiled into a template rather than mounted as a component, so a
 * dismissible banner in a form view has nothing to hold state and no component
 * to hang a handler on. One delegated listener therefore covers every such
 * alert on the page — the same shape the tooltip service already uses for
 * `data-tooltip`.
 *
 * Alerts inside an OWL template do not need this: there, `t-on-click` against
 * component state is both clearer and reactive.
 *
 *   <button class="btn-close" data-dismiss-alert="1" aria-label="Close"/>
 */
export const dismissAlertService = {
    start() {
        /** @param {MouseEvent} ev */
        const onClick = (ev) => {
            const target = /** @type {Element} */ (ev.target);
            const trigger = target?.closest?.("[data-dismiss-alert]");
            if (!trigger) {
                return;
            }
            // The triggers are typically `<a href="#">`, whose default would
            // otherwise push a history entry on the way out.
            ev.preventDefault();
            trigger.closest(".alert")?.remove();
        };

        whenReady(() => document.body.addEventListener("click", onClick));

        return {
            /** Service-teardown hook: the listener outlives the env otherwise. */
            destroy() {
                document.body.removeEventListener("click", onClick);
            },
        };
    },
};

registry.category("services").add("dismiss_alert", dismissAlertService);
