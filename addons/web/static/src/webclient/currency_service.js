// @ts-check
/** @odoo-module native */

/** @module @web/webclient/currency_service - Service that auto-reloads currencies when res.currency records are mutated */

import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { currencies } from "@web/services/currency";
import { UPDATE_METHODS } from "@web/services/orm_service";

/** Service that reloads currencies when res.currency records are mutated. */
export const currencyService = {
    dependencies: ["orm"],
    // ``async`` lookup matches by exact key — must match the camelCase
    // method name below. A former snake_case typo here made the
    // destroy-protection wrapper in ``hooks.js:_protectMethod`` skip
    // wrapping, so ``odoo_fin_connector.js`` leaked results from the raw
    // promise into destroyed components.
    async: ["reloadCurrencies"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: import("@web/services/orm_service").ORM }} services
     * @returns {{ reloadCurrencies: () => Promise<void> }}
     */
    start(env, { orm }) {
        // Monotonic fetch generation: two rapid res.currency mutations fire two
        // overlapping reloads whose responses can resolve out of order; without
        // this the later-arriving OLDER snapshot would win the delete+assign
        // swap, showing a stale rate/decimal config until the next mutation.
        // Same precedent as menu_service's fetchGeneration.
        let fetchGeneration = 0;
        /** Reload currencies from the server, replacing the in-memory cache. */
        async function reloadCurrencies() {
            const generation = ++fetchGeneration;
            const result = await orm.call("res.currency", "get_all_currencies");
            if (generation !== fetchGeneration) {
                // A newer reload was started while this one was in flight; its
                // result supersedes ours, so don't clobber it with stale data.
                return;
            }
            for (const k of Object.keys(currencies)) {
                delete currencies[k];
            }
            Object.assign(currencies, result);
        }
        rpcBus.addEventListener(RpcEvent.RESPONSE, (ev) => {
            // Defensive: malformed payloads (null detail, missing data) can
            // be dispatched to the global rpcBus by tests or synthetic fires;
            // don't let that throw and pollute other tests via the shared bus.
            if (!ev.detail?.data?.params) {
                return;
            }
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (!error && model === "res.currency" && UPDATE_METHODS.includes(method)) {
                // Fire-and-forget background refresh: a failed
                // ``get_all_currencies`` must not become an unhandled
                // rejection (→ user-facing error dialog) for what is only a
                // best-effort cache update. Mirror the menu-revalidation
                // pattern and just log it.
                reloadCurrencies().catch(console.warn);
            }
        });
        return { reloadCurrencies };
    },
};

registry.category("services").add("currency", currencyService);
