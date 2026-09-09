// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

/** @type {{ */
export const allowedQwebExpressionsService = {
    dependencies: ["orm"],
    async: true,
    start(env, { orm }) {
        /** @type {Map<string, Promise<string[]>>} */
        const cache = new Map();
        return (resModel) => {
            const cached = cache.get(resModel);
            if (cached) {
                return cached;
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
