// @ts-check
/** @odoo-module native */

/** @module @web/ui/effects/effect_service - Service that triggers visual effects (rainbow man) via the effects registry */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

import { RainbowMan } from "./rainbow_man.js";

const effectRegistry = registry.category("effects");

// RainbowMan effect

/**
 * Handles effect of type "rainbow_man": returns the RainbowMan component and
 * props to instantiate, or (if effects are disabled) shows a notification.
 *
 * @param {import("@web/env").OdooEnv} env
 * @param {Object} [params={}]
 * @param {string} [params.message="Well Done!"] Notice text (or HTML string) the rainbowman holds, or the notification content if effects are disabled.
 * @param {string} [params.img_url="/web/static/img/smile.svg"] Image shown inside the rainbow.
 * @param {"slow"|"medium"|"fast"|"no"} [params.fadeout="medium"] Delay before the rainbowman disappears; "no" keeps it until the user clicks outside it.
 * @param {import("@odoo/owl").ComponentConstructor} [params.Component] Custom component to instantiate inside the Rainbow Man.
 * @param {Object} [params.props] Props for `params.Component`, if given.
 */
function rainbowMan(env, params = {}) {
    let message = params.message;
    if (/** @type {any} */ (message) instanceof Element) {
        console.warn(
            "Providing an HTML element to an effect is deprecated. Note that all event handlers will be lost.",
        );
        message = message.outerHTML;
    } else if (!message) {
        message = _t("Well Done!");
    }
    if (user.showEffect) {
        /** @type {import("./rainbow_man").RainbowManProps} */
        const props = {
            imgUrl: params.img_url || "/web/static/img/smile.svg",
            fadeout: params.fadeout || "medium",
            message,
            Component: params.Component,
            props: params.props,
        };
        return { Component: RainbowMan, props };
    }
    env.services.notification.add(message);
}
effectRegistry.add("rainbow_man", rainbowMan);

// Effects are called as `effect(env, params)`; validating here turns a bad
// registration into a clear error instead of a downstream `TypeError`.
// Throws in debug, warns in production (see `registry.js validateSchema`).
effectRegistry.addValidation((v) => typeof v === "function");

// Effect service

/** Service for triggering visual effects (e.g. rainbow man) via the effects registry. */
export const effectService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ overlay: any }} services
     */
    start(env, { overlay }) {
        /**
         * @param {Object} [params] various params depending on the type of effect
         * @param {string} [params.type="rainbow_man"] the effect to display
         */
        const add = (params = {}) => {
            const type = params.type || "rainbow_man";
            if (!effectRegistry.contains(type)) {
                // `type` can come from a server effect payload; an unknown type
                // would make `effectRegistry.get` throw and blow up the caller.
                // Warn and no-op instead.
                console.warn(`[effect] unknown effect type "${type}"; ignoring.`);
                return;
            }
            const effect = effectRegistry.get(type);
            const { Component, props } = effect(env, params) || {};
            if (Component) {
                const remove = overlay.add(Component, {
                    ...props,
                    close: () => remove(),
                });
            }
        };

        return { add };
    },
};

registry.category("services").add("effect", effectService);
