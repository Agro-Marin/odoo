/** @odoo-module native */
import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { UPDATE_METHODS } from "@web/services/orm_service";
import { rpcBus } from "@web/core/network/rpc";

registry.category("services").add("stock_warehouse", {
    dependencies: ["action"],
    start(env, { action }) {
        rpcBus.addEventListener("RPC:RESPONSE", (ev) => {
            // Defensive: malformed payloads (null detail, missing data,
            // missing params) can be dispatched to the global rpcBus by
            // tests or synthetic fires. Optional-chain before destructuring
            // so this listener does not turn a malformed event into a
            // thrown exception that pollutes other tests via the shared bus.
            if (!ev.detail?.data?.params) {
                return;
            }
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (!error && model === "stock.warehouse") {
                if (UPDATE_METHODS.includes(method) && !browser.localStorage.getItem("running_tour")) {
                    action.doAction("reload_context");
                }
            }
        });
    },
});
