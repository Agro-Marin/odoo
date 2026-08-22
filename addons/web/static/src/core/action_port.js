// @ts-check
/** @odoo-module native */

import { useService } from "@web/core/utils/hooks";

/**
 * @typedef {Pick<
 * import("services").ServiceFactories["action"],
 * "doAction" | "doActionButton" | "switchView"
 * >} ActionPort
 */

/**
 * @returns {ActionPort}
 */
export function useAction() {
    return useService("action");
}

/**
 * @param {import("@web/env").OdooEnv} env
 * @returns {ActionPort}
 */
export function getAction(env) {
    return env.services.action;
}
