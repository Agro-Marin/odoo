// @ts-check
/** @odoo-module native */

/** @module @web/webclient/currency_service - Service that auto-reloads currencies when res.currency records are mutated */

import { onModelMutation } from "@web/core/network/model_mutation";
import { registry } from "@web/core/registry";
import { currencies } from "@web/services/currency";

/** Service that reloads currencies when res.currency records are mutated. */
export const currencyService = {
    dependencies: ["orm"],
    async: ["reloadCurrencies"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: import("@web/services/orm_service").ORM }} services
     * @returns {{ reloadCurrencies: () => Promise<void> }}
     */
    start(env, { orm }) {
        let fetchGeneration = 0;
        /** Reload currencies from the server, replacing the in-memory cache. */
        async function reloadCurrencies() {
            const generation = ++fetchGeneration;
            const result = await orm.call("res.currency", "get_all_currencies");
            if (generation !== fetchGeneration) {
                return;
            }
            for (const k of Object.keys(currencies)) {
                delete currencies[k];
            }
            Object.assign(currencies, result);
        }
        onModelMutation(["res.currency"], () => {
            reloadCurrencies().catch(console.warn);
        });
        return { reloadCurrencies };
    },
};

registry.category("services").add("currency", currencyService);
