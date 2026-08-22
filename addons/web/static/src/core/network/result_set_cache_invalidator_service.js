// @ts-check
/** @odoo-module native */

import { RpcEvent } from "@web/core/events";
import { onModelMutation } from "@web/core/network/model_mutation";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

export const RESULT_SET_REMOVING_METHODS = new Set([
    "unlink",
    "action_archive",
    "action_unarchive",
]);

const RESULT_SET_TABLES = ["web_read", "web_search_read", "web_read_group"];

const resultSetCacheInvalidatorService = {
    /**
     * @param {import("@web/env").OdooEnv} _env
     */
    start(_env) {
        const disposers = [
            onModelMutation(
                () => true,
                ({ model }) =>
                    rpcBus.trigger(RpcEvent.CLEAR_CACHES, {
                        tables: RESULT_SET_TABLES,
                        model,
                    }),
                { methods: RESULT_SET_REMOVING_METHODS },
            ),
            onModelMutation(
                ["base.language.install"],
                () => rpcBus.trigger(RpcEvent.CLEAR_CACHES),
                { methods: ["lang_install"] },
            ),
        ];

        return {
            destroy() {
                for (const dispose of disposers) {
                    dispose();
                }
            },
        };
    },
};

registry
    .category("services")
    .add("result_set_cache_invalidator", resultSetCacheInvalidatorService);
