// @ts-check
/** @odoo-module native */

/** @module @web/ui/effects/effect_service */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

import { RainbowMan } from "./rainbow_man.js";

const effectRegistry = registry.category("effects");

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Object} [params={}]
 * @param {string} [params.message="Well Done!"]
 * @param {string} [params.img_url="/web/static/img/smile.svg"]
 * @param {"slow"|"medium"|"fast"|"no"} [params.fadeout="medium"]
 * @param {import("@odoo/owl").ComponentConstructor} [params.Component]
 * @param {Object} [params.props]
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

effectRegistry.addValidation((v) => typeof v === "function");

export const effectService = {
    dependencies: ["overlay"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ overlay: any }} services
     */
    start(env, { overlay }) {
        /**
         * @param {Object} [params]
         * @param {string} [params.type="rainbow_man"]
         */
        const add = (params = {}) => {
            const type = params.type || "rainbow_man";
            if (!effectRegistry.contains(type)) {
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
