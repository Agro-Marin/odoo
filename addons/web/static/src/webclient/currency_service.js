// @ts-check
/** @odoo-module native */

import { currencies } from "@web/core/currency";
import { onModelMutation } from "@web/core/network/model_mutation";
import { registry } from "@web/core/registry";

class CurrencyService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: import("@web/core/network/orm_service").ORM }} services
     */
    constructor(env, { orm }) {
        this.env = env;
        this.orm = orm;
        this.fetchGeneration = 0;
        this.stopWatching = onModelMutation(["res.currency"], () => {
            this.reloadCurrencies().catch(console.warn);
        });
    }

    /** @returns {Promise<void>} */
    async reloadCurrencies() {
        const generation = ++this.fetchGeneration;
        const result = await this.orm.call("res.currency", "get_all_currencies");
        if (generation !== this.fetchGeneration) {
            return;
        }
        for (const key of Object.keys(currencies)) {
            delete currencies[Number(key)];
        }
        Object.assign(currencies, result);
    }

    destroy() {
        this.stopWatching();
        this.stopWatching = () => {};
    }
}

const currencyService = {
    dependencies: ["orm"],
    async: ["reloadCurrencies"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: import("@web/core/network/orm_service").ORM }} services
     * @returns {CurrencyService}
     */
    start(env, services) {
        return new CurrencyService(env, services);
    },
};

registry.category("services").add("currency", currencyService);
