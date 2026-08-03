// @ts-check
/** @odoo-module native */

/** @module @web/webclient/currency_service */

import { currencies } from "@web/core/currency";
import { onModelMutation } from "@web/core/network/model_mutation";
import { registry } from "@web/core/registry";

export const currencyService = {
    dependencies: ["orm"],
    async: ["reloadCurrencies"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: import("@web/core/network/orm_service").ORM }} services
     * @returns {{ reloadCurrencies: () => Promise<void> }}
     */
    start(env, { orm }) {
        let fetchGeneration = 0;
        async function reloadCurrencies() {
            const generation = ++fetchGeneration;
            const result = await orm.call("res.currency", "get_all_currencies");
            if (generation !== fetchGeneration) {
                return;
            }
            for (const k of Object.keys(currencies)) {
                delete currencies[Number(k)];
            }
            Object.assign(currencies, result);
        }
        const currencyServiceApi = { reloadCurrencies };
        // Facade-routed so a downstream patch of `reloadCurrencies` is seen by
        // this listener too; calling the closure would capture the pre-patch fn.
        onModelMutation(["res.currency"], () => {
            currencyServiceApi.reloadCurrencies().catch(console.warn);
        });
        return currencyServiceApi;
    },
};

registry.category("services").add("currency", currencyService);
