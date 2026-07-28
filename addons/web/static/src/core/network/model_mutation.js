// @ts-check
/** @odoo-module native */

/** @module @web/core/network/model_mutation - Subscribe to mutating RPCs on the shared rpcBus */

import { RpcEvent } from "@web/core/events";
import { rpcBus, RPCError } from "@web/core/network/rpc";

/**
 * Methods that mutate server state, as far as cache-invalidation consumers are
 * concerned.
 *
 * Lives next to ``rpcBus`` rather than in ``@web/services/orm_service``: every
 * consumer is a bus listener, and none of them needs the ``ORM`` class. Routing
 * them through the service module pulled ``Domain``, ``rpc`` and ``user`` into
 * modules that only ever wanted this array.
 */
export const UPDATE_METHODS = [
    "unlink",
    "create",
    "write",
    "web_save",
    "web_save_multi",
    "action_archive",
    "action_unarchive",
];

/**
 * Subscribe to mutating RPCs targeting the given models.
 *
 * Seven consumers used to hand-roll this decode against the raw ``rpcBus``
 * (``action_cache_invalidation``, ``views/view_service``, ``currency_service``,
 * ``reload_company_service``, ``analytic``'s ``reload_analytic_plan``,
 * ``stock_warehouse``, ``web_studio``'s approval-rule cache clear) and had
 * drifted into three different, all-wrong policies for *failed* mutations. The
 * subtle part lives here once.
 *
 * INVARIANT — error policy. A mutation whose RPC failed splits in two:
 *
 * - ``RPCError`` — the server raised, so the transaction was rolled back and
 *   nothing changed. Reacting is pure waste (a dropped cache and extra
 *   round-trips right after the user already got an error dialog). Skipped.
 * - Any other failure (``ConnectionLostError``, timeout, abort, session
 *   expiry) — the request may well have reached the server and COMMITTED; only
 *   the response was lost. Skipping here would leave a stale cache with no
 *   other trigger for the rest of the session, so these DO fire.
 *
 * The default therefore errs toward reacting: an unnecessary cache flush costs
 * a refetch, a missed one serves wrong data indefinitely. Callers whose
 * reaction is disruptive rather than merely costly (e.g. forcing a full page
 * reload) opt out with ``successOnly``.
 *
 * @param {string[] | ((model: string) => boolean)} models model names to watch,
 *   or a predicate over the model name
 * @param {(info: {model: string, method: string, error?: any}) => void} handler
 * @param {object} [options]
 * @param {boolean} [options.successOnly=false] fire only when the mutation is
 *   known to have succeeded, dropping the "may have committed" failures above.
 * @param {Iterable<string>} [options.methods] narrow (or replace) the watched
 *   method set, which defaults to {@link UPDATE_METHODS}. Use it for consumers
 *   that react to a subset (``result_set_cache_invalidator`` only cares about
 *   record-REMOVING methods) or to a mutation outside the CRUD set
 *   (``base.language.install``'s ``lang_install``). Narrowing here rather than
 *   re-testing inside the handler keeps the error policy above — the subtle
 *   part — in one place.
 * @returns {() => void} disposer removing the ``rpcBus`` listener. Session-lived
 *   consumers may ignore it; anything shorter-lived MUST call it (see
 *   ``installActionCacheInvalidation``).
 */
export function onModelMutation(
    models,
    handler,
    { successOnly = false, methods = UPDATE_METHODS } = {},
) {
    const watchedModels = typeof models === "function" ? null : new Set(models);
    const matches = watchedModels
        ? (/** @type {string} */ model) => watchedModels.has(model)
        : /** @type {(model: string) => boolean} */ (models);
    const watchedMethods = new Set(methods);
    const onResponse = (/** @type {any} */ ev) => {
        const params = ev.detail?.data?.params;
        if (!params) {
            return;
        }
        const { model, method } = params;
        if (typeof model !== "string" || !matches(model)) {
            return;
        }
        if (!watchedMethods.has(method)) {
            return;
        }
        const { error } = ev.detail;
        const isServerRejection =
            error instanceof RPCError || error?.name === "RPC_ERROR";
        if (error && (successOnly || isServerRejection)) {
            return;
        }
        handler({ model, method, error });
    };
    rpcBus.addEventListener(RpcEvent.RESPONSE, onResponse);
    return () => rpcBus.removeEventListener(RpcEvent.RESPONSE, onResponse);
}
