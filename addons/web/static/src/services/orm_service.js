// @ts-check
/** @odoo-module native */

/** @module @web/services/orm_service - ORM RPC client for CRUD, read_group, and x2many command helpers */

import { Domain } from "@web/core/domain";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

/**
 * Standard way to interact with the Python ORM from the javascript codebase.
 */

// -----------------------------------------------------------------------------
// ORM
// -----------------------------------------------------------------------------

/**
 * @param {any} value
 */
function validateModel(value) {
    if (typeof value !== "string" || !value.length) {
        throw new Error(`Invalid model name: ${value}`);
    }
}
/**
 * @param {string} name
 * @param {string} type
 * @param {any} value
 */
function validatePrimitiveList(name, type, value) {
    if (!Array.isArray(value) || value.some((val) => typeof val !== type)) {
        throw new Error(`Invalid ${name} list: ${value}`);
    }
}
/**
 * @param {string} name
 * @param {any} obj
 */
function validateObject(name, obj) {
    if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
        throw new Error(`${name} should be an object`);
    }
}
/**
 * @param {string} name
 * @param {any} array
 */
function validateArray(name, array) {
    if (!Array.isArray(array)) {
        throw new Error(`${name} should be an array`);
    }
}

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
 * Methods that mutate server state. ``retry``/``dedup``/``cache`` are
 * hard-rejected for these: a retried partial mutation could be re-applied
 * server-side, deduplication would conflate two distinct caller invocations
 * that happen to share a payload, and caching would store the write's result
 * and serve a later identical write from cache without hitting the server.
 * Superset of {@link UPDATE_METHODS} (which is scoped to cache-invalidation
 * consumers and intentionally left untouched).
 *
 * ``copy`` is included explicitly: it duplicates records (a mutation) but is
 * NOT in ``UPDATE_METHODS`` (which drives cache invalidation, where copy is
 * handled by the returned record's own read). Without it,
 * ``orm.retry(1).call(model, "copy", [ids])`` would slip through the guard and
 * a retry after a lost response could create duplicate records.
 *
 * NOTE — a full inversion to an idempotent-read WHITELIST (rejecting every
 * method not known to be a safe read) is deliberately DEFERRED: the ``call``
 * escape hatch is used with legitimately-cacheable CUSTOM read methods
 * (e.g. enterprise ``ai.agent.get_ask_ai_agent`` via ``orm.cache().call``),
 * which a hard-throw whitelist in this base module cannot enumerate and would
 * break at runtime. A safe inversion needs a caller-side idempotence opt-in
 * (e.g. ``orm.idempotent.call(...)``) plus migrating those custom callers —
 * out of scope here. Until then the blacklist stays authoritative; add any
 * newly-discovered mutating method here.
 */
const NON_IDEMPOTENT_METHODS = [
    ...UPDATE_METHODS,
    "web_resequence",
    "name_create",
    "copy",
    // Flips ``active`` on the records (odoo/orm/models/mixins/lifecycle.py):
    // a retry after a lost response would double-flip the archive state.
    "toggle_active",
];

export class ORM {
    constructor() {
        this.rpc = rpc; // to be overridable by the SampleORM
        /** @protected */
        this._silent = false;
        this._cache = false;
        this._retry = false;
        this._dedup = false;
    }

    /** @returns {ORM} */
    get silent() {
        return Object.assign(Object.create(this), { _silent: true });
    }

    /**
     * @param {object} options
     * @returns {ORM}
     */
    cache(options = {}) {
        return Object.assign(Object.create(this), { _cache: options });
    }

    /**
     * Opt-in: identical concurrent (url, params) share a single in-flight
     * promise. Useful for non-cached idempotent reads fired by multiple
     * components on the same record (e.g. a form and its sidebar both
     * reading the same partner during a mount cascade).
     *
     * Redundant on top of ``cache({type:"disk"|"ram"})``, which already dedupes via
     * ``RPCCache.pendingRequests`` — apply ``.dedup`` to uncached reads only.
     * Abort is shared: aborting one caller's promise cancels the underlying
     * fetch and rejects every other caller with ``ConnectionAbortedError``;
     * don't opt in if you need independent abort lifecycles.
     *
     * Never apply to writes — identical payloads are still distinct calls.
     *
     * @returns {ORM}
     */
    get dedup() {
        return Object.assign(Object.create(this), { _dedup: true });
    }

    /**
     * Opt-in exponential-backoff retry, for idempotent reads that benefit
     * from resilience to transient failures (proxy hiccup, pool exhaustion,
     * brief network blip):
     *
     *     orm.retry(1).webSearchRead("res.partner", domain, {});
     *     orm.retry({ retries: 3, baseMs: 100 }).read(...);
     *
     * Caller must ensure the call is safe to retry — never apply to writes
     * (create/write/unlink/web_save/...), which could re-apply a partial
     * server-side mutation.
     *
     * @param {number | { retries?: number, baseMs?: number, maxMs?: number }} [options=1]
     *   Default matches the boot-path budget in CONVENTIONS.md (~200ms, one
     *   backoff interval); raise only for background paths the user can't see.
     * @returns {ORM}
     */
    retry(options = 1) {
        return Object.assign(Object.create(this), { _retry: options });
    }

    /**
     * @param {string} model
     * @param {string} method
     * @param {any[]} [args=[]]
     * @param {any} [kwargs={}]
     * @returns {Promise<any>}
     */
    call(model, method, args = [], kwargs = {}) {
        validateModel(model);
        if (NON_IDEMPOTENT_METHODS.includes(method)) {
            // Turn the "never apply to writes" docstring convention into a
            // hard contract: fail at call time, before anything reaches the
            // network, instead of after a double-applied mutation.
            if (this._retry) {
                throw new Error(
                    `orm.retry() cannot be applied to mutating method "${method}": ` +
                        `a retry could re-apply a partially-committed server mutation`,
                );
            }
            if (this._dedup) {
                throw new Error(
                    `orm.dedup cannot be applied to mutating method "${method}": ` +
                        `identical payloads are still distinct invocations for writes`,
                );
            }
            if (this._cache) {
                throw new Error(
                    `orm.cache() cannot be applied to mutating method "${method}": ` +
                        `the write's result would be stored and a later identical ` +
                        `write served from cache without ever reaching the server`,
                );
            }
        }
        const url = `/web/dataset/call_kw/${model}/${method}`;
        const fullContext = { ...user.context, ...(kwargs.context || {}) };
        const fullKwargs = { ...kwargs, context: fullContext };
        const params = {
            model,
            method,
            args,
            kwargs: fullKwargs,
        };
        return this.rpc(url, params, {
            silent: this._silent,
            cache: this._cache,
            retry: this._retry,
            dedup: this._dedup,
        });
    }

    /**
     * @param {string} model
     * @param {any[]} records
     * @param {any} [kwargs=[]]
     * @returns {Promise<number>}
     */
    create(model, records, kwargs = {}) {
        validateArray("records", records);
        for (const record of records) {
            validateObject("record", record);
        }
        return this.call(model, "create", [records], kwargs);
    }

    /**
     * @param {string} model
     * @param {number[]} ids
     * @param {string[]} fields
     * @param {any} [kwargs={}]
     * @returns {Promise<any[]>}
     */
    read(model, ids, fields, kwargs = {}) {
        validatePrimitiveList("ids", "number", ids);
        if (fields) {
            validatePrimitiveList("fields", "string", fields);
        }
        if (!ids.length) {
            return Promise.resolve([]);
        }
        return this.call(model, "read", [ids, fields], kwargs);
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {string[]} groupby
     * @param {string[]} aggregates
     * @param {any} [kwargs={}]
     * @returns {Promise<any[]>}
     */
    async formattedReadGroup(model, domain, groupby, aggregates, kwargs = {}) {
        validateArray("domain", domain);
        validatePrimitiveList("groupby", "string", groupby);
        validatePrimitiveList("aggregates", "string", aggregates);
        const res = await this.call(model, "formatted_read_group", [], {
            domain,
            groupby,
            aggregates,
            ...kwargs,
        });
        // Build ``__domain`` on a SHALLOW COPY of each group instead of mutating
        // the RPC result in place: under ``orm.cache({immutable:true})`` the
        // payload is deep-frozen and shared across warm hits, so an in-place
        // ``group.__domain = ...`` throws a TypeError in strict mode (and would
        // otherwise cross-contaminate every future cache reader).
        return res.map((group) => ({
            ...group,
            __domain: Domain.and([domain, group["__extra_domain"]]).toList(),
        }));
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {string[][]} grouping_sets
     * @param {string[]} aggregates
     * @param {any} [kwargs={}]
     * @returns {Promise<any[]>}
     */
    async formattedReadGroupingSets(
        model,
        domain,
        grouping_sets,
        aggregates,
        kwargs = {},
    ) {
        validateArray("domain", domain);
        validateArray("grouping_sets", grouping_sets);
        validatePrimitiveList("aggregates", "string", aggregates);
        const res = await this.call(model, "formatted_read_grouping_sets", [], {
            domain,
            grouping_sets,
            aggregates,
            ...kwargs,
        });
        // Shallow-copy each group rather than mutate the (possibly deep-frozen,
        // shared) RPC result in place — see ``formattedReadGroup`` above.
        return res.map((groups) =>
            groups.map((group) => ({
                ...group,
                __domain: Domain.and([domain, group["__extra_domain"]]).toList(),
            })),
        );
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {any} [kwargs={}]
     * @returns {Promise<any[]>}
     */
    search(model, domain, kwargs = {}) {
        validateArray("domain", domain);
        return this.call(model, "search", [domain], kwargs);
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {string[]} fields
     * @param {any} [kwargs={}]
     * @returns {Promise<any[]>}
     */
    searchRead(model, domain, fields, kwargs = {}) {
        validateArray("domain", domain);
        if (fields) {
            validatePrimitiveList("fields", "string", fields);
        }
        return this.call(model, "search_read", [], {
            ...kwargs,
            domain,
            fields,
        });
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {any} [kwargs={}]
     * @returns {Promise<number>}
     */
    searchCount(model, domain, kwargs = {}) {
        validateArray("domain", domain);
        return this.call(model, "search_count", [domain], kwargs);
    }

    /**
     * @param {string} model
     * @param {number[]} ids
     * @param {any} [kwargs={}]
     * @returns {Promise<boolean>}
     */
    unlink(model, ids, kwargs = {}) {
        validatePrimitiveList("ids", "number", ids);
        if (!ids.length) {
            return Promise.resolve(true);
        }
        return this.call(model, "unlink", [ids], kwargs);
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {string[]} groupby
     * @param {string[]} aggregates
     * @param {any} [kwargs={}]
     * @returns {Promise<any[]>}
     */
    webReadGroup(model, domain, groupby, aggregates, kwargs = {}) {
        validateArray("domain", domain);
        validatePrimitiveList("aggregates", "string", aggregates);
        return this.call(model, "web_read_group", [], {
            domain,
            groupby,
            aggregates,
            ...kwargs,
        });
    }

    /**
     * @param {string} model
     * @param {number[]} ids
     * @param {object} [kwargs={}]
     * @param {Object} [kwargs.specification]
     * @param {Object} [kwargs.context]
     * @returns {Promise<any[]>}
     */
    webRead(model, ids, kwargs = {}) {
        validatePrimitiveList("ids", "number", ids);
        return this.call(model, "web_read", [ids], kwargs);
    }

    /**
     * @param {string} model
     * @param {number[]} ids
     * @param {object} [kwargs={}]
     * @param {object} [kwargs.context]
     * @param {string} [kwargs.field_name]
     * @param {number} [kwargs.offset]
     * @param {object} [kwargs.specification]
     * @returns {Promise<any[]>}
     */
    webResequence(model, ids, kwargs = {}) {
        validatePrimitiveList("ids", "number", ids);
        return this.call(model, "web_resequence", [ids], {
            ...kwargs,
            specification: kwargs.specification || {},
        });
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {any} [kwargs={}]
     * @returns {Promise<any[]>}
     */
    webSearchRead(model, domain, kwargs = {}) {
        validateArray("domain", domain);
        return this.call(model, "web_search_read", [], { ...kwargs, domain });
    }

    /**
     * @param {string} model
     * @param {number[]} ids
     * @param {any} data
     * @param {any} [kwargs={}]
     * @returns {Promise<boolean>}
     */
    write(model, ids, data, kwargs = {}) {
        validatePrimitiveList("ids", "number", ids);
        validateObject("data", data);
        return this.call(model, "write", [ids, data], kwargs);
    }

    /**
     * @param {string} model
     * @param {number[]} ids
     * @param {any} data
     * @param {object} [kwargs={}]
     * @param {Object} [kwargs.specification]
     * @param {Object} [kwargs.context]
     * @returns {Promise<any[]>}
     */
    webSave(model, ids, data, kwargs = {}) {
        validatePrimitiveList("ids", "number", ids);
        validateObject("data", data);
        return this.call(model, "web_save", [ids, data], kwargs);
    }

    /**
     * @param {string} model
     * @param {number[]} ids
     * @param {Object[]} data
     * @param {Object} [kwargs={}]
     * @param {Object} [kwargs.specification]
     * @param {Object} [kwargs.context]
     * @returns {Promise<any[]>}
     */
    webSaveMulti(model, ids, data, kwargs = {}) {
        validatePrimitiveList("ids", "number", ids);
        validateArray("data", data);
        data.forEach((d) => {
            validateObject("data item", d);
        });
        return this.call(model, "web_save_multi", [ids, data], kwargs);
    }
}

/**
 * ``orm.silent`` sets ``settings.silent`` on the RPC, which ONLY suppresses
 * the request's UI *progress* affordances: the loading indicator
 * (loading_indicator.js) and the slow-RPC notification (slow_rpc_service.js).
 * It does NOT suppress error dialogs -- nothing in the error pipeline
 * (error_service.js / error_handlers.js) inspects ``silent`` -- so a failing
 * ``orm.silent`` call still surfaces its error. Use it for background/polling
 * reads that shouldn't flash the spinner:
 *
 * this.orm = useService('orm');
 * ...
 * const result = await this.orm.silent.read('res.partner', [id]);
 */
export const ormService = {
    async: [
        "call",
        "create",
        "formattedReadGroup",
        "formattedReadGroupingSets",
        "read",
        "search",
        "searchCount",
        "searchRead",
        "unlink",
        "webRead",
        "webReadGroup",
        "webResequence",
        "webSave",
        "webSaveMulti",
        "webSearchRead",
        "write",
    ],
    start() {
        return new ORM();
    },
};

registry.category("services").add("orm", ormService);
