// @ts-check
/** @odoo-module native */
import { reactive, toRaw } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

/**
 * The store mirrors the localStorage keys the mail client reads in a plain object,
 * `store.localStorageValues`, so a record compute that reads a key through
 * `readLocalStorageItem(this.store, key)` recomputes when another tab writes it (the
 * `storage` event) or this tab does (`setLocalStorageItem`) -- no per-key counter to
 * bump, no per-model `storage` listener.
 */

/** @typedef {import("models").Store} Store */

/**
 * @param {Store} store
 * @returns {Store}
 */
function rawStore(store) {
    return toRaw(store)._raw;
}

/**
 * @param {Store} store
 * @param {StorageEvent} ev
 */
function onStorageEvent(store, ev) {
    const raw = rawStore(store);
    const values = reactive(raw.localStorageValues);
    const keys = ev.key === null ? Object.keys(raw.localStorageValues) : [ev.key];
    for (const key of keys) {
        if (key in raw.localStorageValues) {
            values[key] = ev.key === null ? null : ev.newValue;
        }
    }
    const notified =
        ev.key === null ? [...raw._localStorageSubscribers.keys()] : [ev.key];
    for (const key of notified) {
        for (const cb of raw._localStorageSubscribers.get(key) ?? []) {
            cb(ev.key === null ? null : ev.newValue);
        }
    }
}

/**
 * From the store's `setup()`, before any compute reads a key.
 * @param {{localStorageValues: Object<string, string|null>, _localStorageSubscribers: Map<string, Set<(newValue: string|null) => void>>}} store
 */
export function initLocalStorageMirror(store) {
    store.localStorageValues = {};
    store._localStorageSubscribers = new Map();
}

/**
 * Once per store, when its service starts; the listener lives as long as the page.
 * @param {Store} store
 */
export function startLocalStorageMirror(store) {
    browser.addEventListener("storage", (ev) => onStorageEvent(store, ev));
}

/**
 * @param {Store} store the caller's reactive `this.store`, so the read subscribes it
 * @param {string} key
 * @returns {string|null}
 */
export function readLocalStorageItem(store, key) {
    const raw = rawStore(store);
    if (!(key in raw.localStorageValues)) {
        raw.localStorageValues[key] = browser.localStorage.getItem(key);
    }
    return store.localStorageValues[key];
}

/**
 * @param {Store} store
 * @param {string} key
 * @param {string} value
 */
export function setLocalStorageItem(store, key, value) {
    browser.localStorage.setItem(key, value);
    reactive(rawStore(store).localStorageValues)[key] = value;
}

/**
 * @param {Store} store
 * @param {string} key
 */
export function removeLocalStorageItem(store, key) {
    browser.localStorage.removeItem(key);
    reactive(rawStore(store).localStorageValues)[key] = null;
}

/**
 * @param {Store} store
 * @param {string} key
 * @param {(newValue: string|null) => void} cb called on a `storage` event for `key`,
 *  or with `null` when another tab clears the storage
 * @returns {() => void}
 */
export function onLocalStorageChange(store, key, cb) {
    const subscribers = rawStore(store)._localStorageSubscribers;
    let set = subscribers.get(key);
    if (!set) {
        set = new Set();
        subscribers.set(key, set);
    }
    set.add(cb);
    return () => {
        set.delete(cb);
        if (set.size === 0) {
            subscribers.delete(key);
        }
    };
}
