// @ts-check
/** @odoo-module native */

/** @module @web/services/result_set_cache_invalidator_service - Bridges `RPC:RESPONSE` for record-removing methods into a scoped `CLEAR-CACHES` event */

import { RpcEvent } from "@web/core/events";
import { onModelMutation } from "@web/core/network/model_mutation";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * Methods that remove records from the model's result sets, so cached
 * ``web_read`` / ``web_search_read`` / ``web_read_group`` entries for the
 * affected model must be cleared (the model can't self-update what no
 * longer exists).
 *
 * Distinct from ``create``/``write``/``web_save``/``web_save_multi``, which
 * return the updated record and let the relational model self-maintain its
 * cache via the normal response path (see Plan-C envelope versioning).
 * Broadly invalidating on every write was tried on 2026-05-17 and reverted:
 * it breaks the create→back-nav stale-then-fresh display tested by
 * ``list_view.test.js`` "cache web_search_read (onUpdate called after
 * another load)". Keep this set narrowly scoped — the D3b regression guard
 * (``list_view_performance.test.js`` "non-removing RPC:RESPONSE does not
 * emit CLEAR-CACHES") asserts every write-class method stays excluded.
 *
 * Exported for tests/downstream addons to introspect without re-defining.
 */
export const RESULT_SET_REMOVING_METHODS = new Set([
    "unlink",
    "action_archive",
    "action_unarchive",
]);

/**
 * Tables (RPC cache namespaces) that hold model-keyed result-set payloads
 * and therefore must be invalidated when any record disappears.
 *
 * Excludes ``get_views`` (action menus, view defs — invalidated by
 * ``view_service`` and the search query mixin on view/filter writes,
 * not by record removal) and ``/web/action/load`` (action defs —
 * invalidated by ``action_service`` on ``ir.actions.act_window`` writes).
 */
const RESULT_SET_TABLES = ["web_read", "web_search_read", "web_read_group"];

/**
 * Translates record-removing RPC responses into model-scoped
 * ``CLEAR-CACHES`` events on the same bus.
 *
 * A service (not a module-load side effect) so each `OdooEnv` gets exactly
 * one listener tied to its own lifecycle, instead of one per mounted
 * ``RelationalModel`` instance (which would amplify CLEAR-CACHES N-fold).
 * It also replaces the previous module-load ``rpcBus.addEventListener`` in
 * ``relational_model.js``, which broke tree-shaking and tied wiring to
 * import order.
 *
 * No dependencies: ``rpcBus`` is a module-scoped singleton from
 * ``@web/core/network/rpc``.
 *
 * Subscribes through {@link onModelMutation} rather than decoding ``rpcBus``
 * by hand. That decode had drifted: it skipped EVERY failed mutation, whereas
 * only a ``RPCError`` proves nothing was committed — a ``ConnectionLostError``
 * or timeout on an ``unlink`` may well have deleted the records server-side,
 * and dropping the event left the result-set caches serving the deleted rows
 * for the rest of the session with no other trigger.
 */
export const resultSetCacheInvalidatorService = {
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
            // Installing a language re-renders every translated payload, so
            // nothing model-scoped is salvageable: clear the caches wholesale.
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
