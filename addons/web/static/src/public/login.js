// @ts-check
/** @odoo-module native */

/** @module @web/public/login - Login form interaction that adds a loading effect on submit */

import { registry } from "@web/core/registry";
import { addLoadingEffect } from "@web/core/utils/dom/ui";

import { Interaction } from "./interaction.js";
export class Login extends Interaction {
    static selector = ".oe_login_form";
    dynamicContent = {
        _root: { "t-on-submit": this.onSubmit },
    };

    /**
     * Applies a loading effect on submit (guards against double-clicks),
     * unless preventDefault() was already called. Wraps preventDefault so a
     * later call removes the effect again.
     *
     * @param {Event} ev
     */
    onSubmit(ev) {
        if (!ev.defaultPrevented) {
            const submitEl = /** @type {HTMLElement} */ (
                ev.currentTarget
            ).querySelector("button[type='submit']");
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
