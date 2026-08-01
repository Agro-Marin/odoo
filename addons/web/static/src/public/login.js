// @ts-check
/** @odoo-module native */

/** @module @web/public/login */

import { registry } from "@web/core/registry";
import { addLoadingEffect } from "@web/core/utils/dom/ui";

import { Interaction } from "./interaction.js";
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
        // the login form carries more than one submit button -- "Log in as
        // superuser" sits next to "Log in" -- and the effect belongs on the one
        // that was pressed, not on whichever comes first in the markup. The
        // fallback covers a submit that names no submitter, such as one raised
        // from script or by a keypress.
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
