// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

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
    const message = params.message || _t("Well Done!");
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
    return { remove: env.services.notification.add(message) };
}
effectRegistry.add("rainbow_man", rainbowMan);

effectRegistry.addValidation((v) => typeof v === "function");

const effectService = {
    dependencies: ["notification", "overlay"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ overlay: any }} services
     */
    start(env, { overlay }) {
        /**
         * @param {{ type?: string, [key: string]: any }} [params]
         * @returns {() => void}
         */
        const add = (params = {}) => {
            const type = params.type || "rainbow_man";
            if (!effectRegistry.contains(type)) {
                console.warn(`[effect] unknown effect type "${type}"; ignoring.`);
                return () => {};
            }
            const effect = effectRegistry.get(type);
            const { Component, props, remove: ownRemove } = effect(env, params) || {};
            if (ownRemove) {
                return ownRemove;
            }
            if (!Component) {
                return () => {};
            }
            const remove = overlay.add(Component, {
                ...props,
                close: () => remove(),
            });
            return remove;
        };

        return { add };
    },
};

registry.category("services").add("effect", effectService);
