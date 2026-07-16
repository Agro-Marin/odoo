/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { UPDATE_METHODS } from "@web/services/orm_service";

registry.category("services").add("stock_warehouse", {
    dependencies: ["action"],
    start(env, { action }) {
        // Coalesce bursts of warehouse writes into a single context reload — a flow
        // that writes stock.warehouse several times in quick succession should not
        // trigger a full reload per response.
        const reloadContext = debounce(() => action.doAction("reload_context"), 300);
        rpcBus.addEventListener("RPC:RESPONSE", (ev) => {
            // Defensive: tests or synthetic fires can dispatch malformed payloads
            // (null detail, missing data/params) on the shared rpcBus. Optional-chain
            // before destructuring so a bad event doesn't throw and pollute other tests.
            if (!ev.detail?.data?.params) {
                return;
            }
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (!error && model === "stock.warehouse") {
                if (
                    UPDATE_METHODS.includes(method) &&
                    !browser.localStorage.getItem("running_tour")
                ) {
                    reloadContext();
                }
            }
        });
    },
});
