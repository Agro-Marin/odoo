// @ts-check
/** @odoo-module native */

import { RpcEvent } from "@web/core/events";
import { rpcBus, RPCError } from "@web/core/network/rpc";

export const UPDATE_METHODS = [
    "unlink",
    "create",
    "write",
    "web_save",
    "web_save_multi",
    "action_archive",
    "action_unarchive",
];

/**
 * @param {string[] | ((model: string) => boolean)} models
 * @param {(info: {model: string, method: string, error?: any}) => void} handler
 * @param {object} [options]
 * @param {boolean} [options.successOnly=false]
 * @param {Iterable<string>} [options.methods]
 * @returns {() => void}
 */
export function onModelMutation(
    models,
    handler,
    { successOnly = false, methods = UPDATE_METHODS } = {},
) {
    const watchedModels = typeof models === "function" ? null : new Set(models);
    const matches = watchedModels
        ? (/** @type {string} */ model) => watchedModels.has(model)
        : /** @type {(model: string) => boolean} */ (models);
    const watchedMethods = new Set(methods);
    const onResponse = (/** @type {any} */ ev) => {
        const params = ev.detail?.data?.params;
        if (!params) {
            return;
        }
        const { model, method } = params;
        if (typeof model !== "string" || !matches(model)) {
            return;
        }
        if (!watchedMethods.has(method)) {
            return;
        }
        const { error } = ev.detail;
        const isServerRejection =
            error instanceof RPCError || error?.name === "RPC_ERROR";
        if (error && (successOnly || isServerRejection)) {
            return;
        }
        handler({ model, method, error });
    };
    rpcBus.addEventListener(RpcEvent.RESPONSE, onResponse);
    return () => rpcBus.removeEventListener(RpcEvent.RESPONSE, onResponse);
}
