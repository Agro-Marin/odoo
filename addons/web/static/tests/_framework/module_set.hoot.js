// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { globals } from "@odoo/hoot";

const { fetch: realFetch } = globals;

//-----------------------------------------------------------------------------
// Internal
//-----------------------------------------------------------------------------

/**
 * @param {Record<any, any>} object
 */
function clearObject(object) {
    for (const key in object) {
        delete object[key];
    }
}

/**
 * Reduce the size of the given field and freeze it.
 *
 * @param {Record<string, unknown>} field
 */
function freezeField(field) {
    delete field.name;
    if (field.groupable) {
        delete field.groupable;
    }
    if (!field.readonly && !field.related) {
        delete field.readonly;
    }
    if (!field.required) {
        delete field.required;
    }
    if (field.searchable) {
        delete field.searchable;
    }
    if (field.sortable) {
        delete field.sortable;
    }
    if (field.store && !field.related) {
        delete field.store;
    }
    return Object.freeze(field);
}

/**
 * Reduce the size of the given model and freeze it.
 *
 * @param {Record<string, unknown>} model
 */
function freezeModel(model) {
    if (model.fields) {
        for (const [fieldName, field] of Object.entries(model.fields)) {
            model.fields[fieldName] = freezeField(field);
        }
        Object.freeze(model.fields);
    }
    if (model.inherit) {
        const inherit = /** @type {any[]} */ (model.inherit);
        if (inherit.length) {
            model.inherit = inherit.filter((m) => m !== "base");
        }
        if (!(/** @type {any[]} */ (model.inherit).length)) {
            delete model.inherit;
        }
    }
    if (model.order === "id") {
        delete model.order;
    }
    if (model.parent_name === "parent_id") {
        delete model.parent_name;
    }
    if (model.rec_name === "name") {
        delete model.rec_name;
    }
    return Object.freeze(model);
}

/**
 * @param {Record<string, unknown>} model
 */
function unfreezeModel(model) {
    const fields = Object.create(null);
    if (model.fields) {
        for (const [fieldName, field] of Object.entries(model.fields)) {
            fields[fieldName] = { ...field };
        }
    }
    return { ...model, fields };
}

//-----------------------------------------------------------------------------
// Constants
//-----------------------------------------------------------------------------

const CSRF_TOKEN = odoo.csrf_token;

/** @type {Record<string, Promise<Response>>} */
const globalFetchCache = Object.create(null);
/** @type {Set<string>} */
const modelsToFetch = new Set();
/** @type {Map<string, Record<string, unknown>>} */
const serverModelCache = new Map();

let nextRpcId = 1e9;

//-----------------------------------------------------------------------------
// Exports
//-----------------------------------------------------------------------------

/**
 * Prepare the test environment by patching registries and removing
 * app-specific services that crash without session state.
 *
 * Must be called BEFORE test modules are imported so that describe/test
 * calls don't encounter stale registry entries.
 */
export function setupTestEnvironment() {
    const { loader } = odoo;
    const registryModule = loader.modules.get("@web/core/registry");
    if (!registryModule?.Registry) {
        return;
    }

    // 1. Allow re-adding registry keys (tests overwrite production entries).
    const origAdd = registryModule.Registry.prototype.add;
    registryModule.Registry.prototype.add = function (key, value, options = {}) {
        return origAdd.call(this, key, value, { ...options, force: true });
    };

    // 2. Remove app-specific services that require runtime state
    //    not available in test context (e.g. pos_config_id).
    const serviceReg = registryModule.registry?.category?.("services");
    if (!serviceReg) {
        return;
    }
    const content = serviceReg.content || {};
    for (const name of [
        "pos_data", "pos", "pos.printer", "pos.barcode_reader",
        "pos.bus", "pos_notification",
        "report", "preparation_display",
    ]) {
        delete content[name];
    }

    // 3. Cascade: remove services whose dependencies are now missing.
    //    Prevents env.js "Some services could not be started" errors.
    //    Registry entries are stored as [sequence, descriptor].
    let changed = true;
    while (changed) {
        changed = false;
        for (const [name, entry] of Object.entries(content)) {
            const svc = Array.isArray(entry) ? entry[1] : entry;
            for (const dep of svc?.dependencies || []) {
                if (dep && !(dep in content)) {
                    delete content[name];
                    changed = true;
                    break;
                }
            }
        }
    }
}

export function clearServerModelCache() {
    serverModelCache.clear();
}

/**
 * @param {Iterable<string>} modelNames
 */
export async function fetchModelDefinitions(modelNames) {
    const namesList = [...modelsToFetch];
    if (namesList.length) {
        const formData = new FormData();
        formData.set("csrf_token", CSRF_TOKEN);
        formData.set("model_names", JSON.stringify(namesList));

        const response = await realFetch("/web/model/get_definitions", {
            body: formData,
            method: "POST",
        });
        if (!response.ok) {
            const [s, some, does] =
                namesList.length === 1
                    ? ["", "this", "does"]
                    : ["s", "some or all of these", "do"];
            const message = `Could not fetch definition${s} for server model${s} "${namesList.join(
                `", "`,
            )}": ${some} model${s} ${does} not exist`;
            throw new Error(message);
        }
        const modelDefs = await response.json();

        for (const [modelName, modelDef] of Object.entries(modelDefs)) {
            serverModelCache.set(modelName, freezeModel(modelDef));
            modelsToFetch.delete(modelName);
        }
    }

    const result = Object.create(null);
    for (const modelName of modelNames) {
        const cached = serverModelCache.get(modelName);
        if (cached) {
            result[modelName] = unfreezeModel(cached);
        }
    }
    return result;
}

/**
 * @param {string | URL} input
 * @param {RequestInit} [init]
 */
export function globalCachedFetch(input, init) {
    if (init?.method && init.method.toLowerCase() !== "get") {
        throw new Error(
            `cannot use a global cached fetch with HTTP method "${init.method}"`,
        );
    }
    const key = String(input);
    if (!(key in globalFetchCache)) {
        globalFetchCache[key] = realFetch(input, init).catch((reason) => {
            delete globalFetchCache[key];
            throw reason;
        });
    }
    return globalFetchCache[key].then((response) => response.clone());
}

/**
 * @param {string} modelName
 */
export function registerModelToFetch(modelName) {
    if (!serverModelCache.has(modelName)) {
        modelsToFetch.add(modelName);
    }
}

/**
 * Toned-down version of the RPC + ORM features since this file cannot depend on
 * them.
 *
 * @param {string} model
 * @param {string} method
 * @param {any[]} args
 * @param {Record<string, any>} kwargs
 */
export async function unmockedOrm(model, method, args, kwargs) {
    const response = await realFetch(`/web/dataset/call_kw/${model}/${method}`, {
        body: JSON.stringify({
            id: nextRpcId++,
            jsonrpc: "2.0",
            method: "call",
            params: { args, kwargs, method, model },
        }),
        headers: {
            "Content-Type": "application/json",
        },
        method: "POST",
    });
    const { error, result } = await response.json();
    if (error) {
        throw error;
    }
    return result;
}
