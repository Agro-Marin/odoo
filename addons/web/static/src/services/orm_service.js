// @ts-check
/** @odoo-module native */

/** @module @web/services/orm_service - ORM RPC client for CRUD, read_group, and x2many command helpers */

import { Domain } from "@web/core/domain";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/services/user";

/**
 * This ORM service is the standard way to interact with the ORM in python from
 * the javascript codebase.
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
 */
const NON_IDEMPOTENT_METHODS = [...UPDATE_METHODS, "web_resequence", "name_create"];

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
     * promise.  Useful for non-cached idempotent reads fired by multiple
     * components on the same record — e.g., a form and its sidebar both
     * issuing ``orm.read("res.partner", [42])`` during a mount cascade.
     *
     * Composition note: ``cache({type:"disk"|"ram"})`` already has its
     * own stampede prevention (``RPCCache.pendingRequests``), so chaining
     * ``.dedup`` onto a cached path is redundant — the cache layer is
     * doing the work.  Apply ``.dedup`` to **uncached** reads where
     * concurrent duplicate fires would otherwise hit the network.
     *
     * Abort semantics are intentionally shared: if any caller aborts the
     * returned promise, the underlying fetch is canceled and every other
     * caller observing the same promise rejects with
     * ``ConnectionAbortedError``.  Callers that need independent abort
     * lifecycles must not opt in.
     *
     * Never apply to writes — write payloads with the same (url, params)
     * are still distinct invocations from the caller's perspective.
     *
     * @returns {ORM}
     */
    get dedup() {
        return Object.assign(Object.create(this), { _dedup: true });
    }

    /**
     * Apply opt-in exponential-backoff retry to subsequent calls.  Use
     * for idempotent reads that benefit from resilience to transient
     * failures (proxy hiccup, pool exhaustion, brief network blip):
     *
     *     orm.retry(1).webSearchRead("res.partner", domain, {});
     *     orm.retry({ retries: 3, baseMs: 100 }).read(...);
     *
     * Caller is responsible for ensuring the call is safe to retry:
     * never apply to writes (create/write/unlink/web_save/...) — a
     * partial server-side mutation could be re-applied.
     *
     * @param {number | { retries?: number, baseMs?: number, maxMs?: number }} [options=1]
     *   Default 1 matches the documented boot-path budget in CONVENTIONS.md
     *   (caps user-perceived delay on persistent outage at one backoff
     *   interval ~200ms).  Higher budgets compound into multi-second hangs
     *   visible as "the app feels frozen"; tune upward only for background
     *   paths the user does not see directly.
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
        for (const group of res) {
            group["__domain"] = Domain.and([domain, group["__extra_domain"]]).toList();
        }
        return res;
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
        for (const groups of res) {
            for (const group of groups) {
                group["__domain"] = Domain.and([
                    domain,
                    group["__extra_domain"],
                ]).toList();
            }
        }
        return res;
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
 * Note:
 *
 * To hide RPC errors, use the following API:
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
