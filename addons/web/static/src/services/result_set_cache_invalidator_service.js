// @ts-check
/** @odoo-module native */

/** @module @web/services/result_set_cache_invalidator_service - Bridges `RPC:RESPONSE` for record-removing methods into a scoped `CLEAR-CACHES` event */

import { RpcEvent } from "@web/core/events";
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
 * ``view_service`` and ``search_query_mutations`` on view/filter writes,
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
 */
export const resultSetCacheInvalidatorService = {
    /**
     * @param {import("@web/env").OdooEnv} _env
     */
    start(_env) {
        const onResponse = (event) => {
            const detail = /** @type {any} */ (event).detail;
            // A failed unlink/archive removed nothing; its RESPONSE carries
            // ``error`` with no ``result``. Skip to avoid a needless reload
            // while the user is retrying.
            if (detail?.error) {
                return;
            }
            const method = detail?.data?.params?.method;
            const model = detail?.data?.params?.model;
            // Language install invalidates virtually everything cached
            // (selections, labels, formats); nuke the whole RPC cache so the
            // new language shows up immediately without an extra reload.
            if (method === "lang_install" && model === "base.language.install") {
                rpcBus.trigger(RpcEvent.CLEAR_CACHES);
                return;
            }
            if (!RESULT_SET_REMOVING_METHODS.has(method)) {
                return;
            }
            rpcBus.trigger(RpcEvent.CLEAR_CACHES, {
                tables: RESULT_SET_TABLES,
                model,
            });
        };

        rpcBus.addEventListener(RpcEvent.RESPONSE, onResponse);

        // ``rpcBus`` is a module-singleton, so the "exactly one listener tied to
        // this env's lifecycle" invariant in the docstring only holds if the
        // listener is actually removed on teardown. Without this, every env ever
        // started leaves a permanent listener and one record removal fires
        // CLEAR-CACHES once PER env — the exact N-fold amplification this
        // service exists to prevent. Called by ``env.destroy()``.
        return {
            destroy() {
                rpcBus.removeEventListener(RpcEvent.RESPONSE, onResponse);
            },
        };
    },
};

registry
    .category("services")
    .add("result_set_cache_invalidator", resultSetCacheInvalidatorService);
