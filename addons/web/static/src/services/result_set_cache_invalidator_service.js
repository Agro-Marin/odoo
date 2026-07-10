// @ts-check
/** @odoo-module native */

/** @module @web/services/result_set_cache_invalidator_service - Bridges `RPC:RESPONSE` for record-removing methods into a scoped `CLEAR-CACHES` event */

import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * Methods that remove records from the model's result sets. The model
 * cannot self-update what no longer exists, so cached
 * ``web_read`` / ``web_search_read`` / ``web_read_group`` entries for the
 * affected model must be cleared.
 *
 * Distinct from ``create`` / ``write`` / ``web_save`` / ``web_save_multi``:
 * those return the updated record and let the relational model self-maintain
 * its cache via the normal response path (see Plan-C envelope versioning).
 * Broadly invalidating on every write was attempted on 2026-05-17 and
 * reverted because it breaks the create→back-nav stale-then-fresh display
 * tested by ``list_view.test.js`` "cache web_search_read (onUpdate called
 * after another load)". Keep this set narrowly scoped.
 *
 * The D3b regression guard (``list_view_performance.test.js`` "non-removing
 * RPC:RESPONSE does not emit CLEAR-CACHES") asserts every write-class
 * method stays excluded.
 *
 * Exported so tests and downstream addons can introspect the active set
 * without re-defining it.
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
 * Why a service and not a module-load side effect:
 *
 * - **Env lifecycle ownership.** Each `OdooEnv` (one per page in
 *   production; one per test in Hoot) gets exactly one listener tied
 *   to its own lifecycle. The framework already serializes
 *   ``startServices`` so the listener is in place before any
 *   user-visible RPC fires.
 * - **No per-model leakage.** The translation logic is stateless and
 *   shared by every ``RelationalModel`` instance on the page; moving
 *   it to ``RelationalModel.setup`` would add one listener per mounted
 *   instance (form + list + embedded x2many + …) and amplify CLEAR-
 *   CACHES emission N-fold.
 * - **Module-load purity.** The previous module-load
 *   ``rpcBus.addEventListener`` in ``relational_model.js`` made the
 *   module non-tree-shakeable and tied wiring to import order. As a
 *   service it shows up in the registry alongside the other RPC-
 *   observability services (``slow_rpc``, ``error``, etc.).
 *
 * No dependencies: ``rpcBus`` is a module-scoped singleton imported
 * directly from ``@web/core/network/rpc``.
 */
export const resultSetCacheInvalidatorService = {
    /**
     * @param {import("@web/env").OdooEnv} _env
     */
    start(_env) {
        rpcBus.addEventListener(RpcEvent.RESPONSE, (event) => {
            const detail = /** @type {any} */ (event).detail;
            // A failed unlink/archive removed nothing (the server rejected it):
            // its RESPONSE carries ``error`` and ``result`` is absent. Emitting
            // CLEAR-CACHES here would needlessly cold-reload the model's
            // list/search-panel data exactly when the user is retrying.
            if (detail?.error) {
                return;
            }
            const method = detail?.data?.params?.method;
            const model = detail?.data?.params?.model;
            // Installing a language is infrequent but invalidates virtually
            // everything cached (selections, translated labels, formats). Rather
            // than scope it, nuke the whole RPC cache so the freshly installed
            // language shows up immediately (e.g. in the user preference form)
            // without an extra reload.
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
        });
    },
};

registry
    .category("services")
    .add("result_set_cache_invalidator", resultSetCacheInvalidatorService);
