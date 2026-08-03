// @ts-check
/** @odoo-module native */

/** @module @web/core/allowed_qweb_expressions_service */

import { registry } from "@web/core/registry";

/**
 * @type {{
 *  dependencies: string[],
 *  async: boolean,
 *  start: (env: any, deps: any) => (resModel: string) => Promise<string[]>,
 * }}
 */
export const allowedQwebExpressionsService = {
    dependencies: ["orm"],
    // The service IS the async function, so `true` is the only way to mark
    // it: a method list has nothing to name.
    async: true,
    start(env, { orm }) {
        /** @type {Map<string, Promise<string[]>>} */
        const cache = new Map();
        return (resModel) => {
            if (cache.has(resModel)) {
                return cache.get(resModel);
            }
            const prom = orm
                .call(resModel, "mail_allowed_qweb_expressions")
                .catch((/** @type {unknown} */ e) => {
                    cache.delete(resModel);
                    return Promise.reject(e);
                });
            cache.set(resModel, prom);
            return prom;
        };
    },
};

registry
    .category("services")
    .add("allowed_qweb_expressions", allowedQwebExpressionsService);
