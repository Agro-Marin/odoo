// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { addLoadingEffect } from "@web/core/utils/dom/ui";
import { Interaction } from "@web/public/interaction";
export class Login extends Interaction {
    static selector = ".oe_login_form";
    dynamicContent = {
        _root: { "t-on-submit": this.onSubmit },
    };

    /**
     * @param {Event} ev
     */
    onSubmit(ev) {
        const rootEl = /** @type {HTMLElement} */ (ev.currentTarget);
        const submitter = /** @type {SubmitEvent} */ (ev).submitter;
        const submitEl =
            submitter instanceof HTMLButtonElement && rootEl.contains(submitter)
                ? submitter
                : rootEl.querySelector("button[type='submit']");
        if (!ev.defaultPrevented && submitEl) {
            const removeLoadingEffect = addLoadingEffect(
                /** @type {HTMLButtonElement} */ (submitEl),
            );
            const oldPreventDefault = ev.preventDefault.bind(ev);
            ev.preventDefault = () => {
                removeLoadingEffect();
                oldPreventDefault();
            };
        }
    }
}

registry.category("public.interactions").add("public.login", Login);
