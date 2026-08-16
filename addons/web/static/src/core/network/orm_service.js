// @ts-check
/** @odoo-module native */

/** @module @web/core/network/orm_service */

import { Domain } from "@web/core/domain";
import { UPDATE_METHODS } from "@web/core/network/model_mutation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

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

const NON_IDEMPOTENT_METHODS = new Set([
    ...UPDATE_METHODS,
    "web_resequence",
    "name_create",
    "copy",
    "toggle_active",
]);

export class ORM {
    constructor() {
        this.rpc = rpc;
        /** @protected */
        this._silent = false;
        this._cache = false;
        this._retry = false;
        this._dedup = false;
        /** @type {AbortSignal | false} */
        this._signal = false;
    }

    /** @returns {ORM} */
    get silent() {
        return Object.assign(Object.create(this), { _silent: true });
    }

    /**
     * Derives an ORM whose calls are cancelled when `signal` aborts.
     *
     * Same proxy pattern as `silent` / `cache()` / `retry()`. Composes with all
     * of them except `dedup`, which `rpc()` refuses alongside a signal because a
     * deduplicated request is shared between callers and cancellation is not.
     *
     * Only ever apply this to reads: an aborted write has already been sent, and
     * cancelling the client's interest in the answer does not undo it.
     *
     * @param {AbortSignal} signal
     * @returns {ORM}
     */
    withSignal(signal) {
        return Object.assign(Object.create(this), { _signal: signal });
    }

    /**
     * @param {object} options
     * @returns {ORM}
     */
    cache(options = {}) {
        return Object.assign(Object.create(this), { _cache: options });
    }

    /**
     * @returns {ORM}
     */
    get dedup() {
        return Object.assign(Object.create(this), { _dedup: true });
    }

    /**
     * @param {number | { retries?: number, baseMs?: number, maxMs?: number }} [options=1]
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
        if (NON_IDEMPOTENT_METHODS.has(method)) {
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
            if (this._signal) {
                throw new Error(
                    `orm.withSignal() cannot be applied to mutating method "${method}": ` +
                        `aborting only drops the client's interest in the response -- ` +
                        `the write has already reached the server and is not undone`,
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
        /** @type {Record<string, any>} */
        const settings = {
            silent: this._silent,
            cache: this._cache,
            retry: this._retry,
            dedup: this._dedup,
        };
        if (this._signal) {
            settings.signal = this._signal;
        }
        return this.rpc(url, params, settings);
    }

    /**
     * `create` takes a LIST of vals and the server answers with the list of ids
     * it made, one per entry -- which is why every call site destructures
     * (`const [id] = await orm.create(...)`), and why export_data_dialog had to
     * cast the result to `any` to do so. The annotation said `number`.
     *
     * @param {string} model
     * @param {any[]} records
     * @param {any} [kwargs=[]]
     * @returns {Promise<number[]>} the new ids, in the order of `records`
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
     * @param {string[]} [fields] Omit to read every field.
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
        /** @type {any[]} */
        const res = await this.call(model, "formatted_read_group", [], {
            ...kwargs,
            domain,
            groupby,
            aggregates,
        });
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
        /** @type {any[][]} */
        const res = await this.call(model, "formatted_read_grouping_sets", [], {
            ...kwargs,
            domain,
            grouping_sets,
            aggregates,
        });
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
     * @returns {Promise<{ groups: any[]; length: number }>}
     */
    webReadGroup(model, domain, groupby, aggregates, kwargs = {}) {
        validateArray("domain", domain);
        validatePrimitiveList("groupby", "string", groupby);
        validatePrimitiveList("aggregates", "string", aggregates);
        return this.call(model, "web_read_group", [], {
            ...kwargs,
            domain,
            groupby,
            aggregates,
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
        if (!ids.length) {
            return Promise.resolve([]);
        }
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
        if (!ids.length) {
            return Promise.resolve([]);
        }
        return this.call(model, "web_resequence", [ids], {
            ...kwargs,
            specification: kwargs.specification || {},
        });
    }

    /**
     * @param {string} model
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {any} [kwargs={}]
     * @returns {Promise<{ records: any[]; length: number }>}
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
    // An empty `ids` means CREATE here, not "nothing to do" — unlike read/unlink
    // this must never short-circuit.
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
