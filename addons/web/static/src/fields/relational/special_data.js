// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/special_data - OWL hook for loading and caching special data tied to a record lifecycle */

import {
    onWillDestroy,
    onWillUpdateProps,
    status,
    useComponent,
    useState,
} from "@odoo/owl";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
/** @import { Component } from "@odoo/owl" */
/** @import { Services } from "services" */

/**
 * Components that must re-run their ``loadFn`` when a shared cache entry turns
 * out to be stale, keyed by the model's ``specialDataCaches`` map and then by
 * cache key.
 *
 * ``specialDataCaches`` deduplicates identical loads across every widget of a
 * view, which is why only the FIRST caller of a key ever reached
 * ``orm.cache(...)`` — and therefore why only that caller's ``callback`` was
 * registered. Every later widget sharing the key (two ``many2many_checkboxes``
 * over the same relation, a ``selection`` and a ``radio`` on the same
 * many2one) got the memoized promise and no subscription, so when the disk
 * cache came back with different data one widget refreshed and its twins kept
 * rendering the stale option list until the next record change.
 *
 * Note the layering: ``rpc_cache.read`` ALREADY multiplexes subscribers over
 * one in-flight request, precisely for this. The dedupe here sits a layer
 * above it and hid that from it, so the fix is to re-establish the fan-out at
 * this layer rather than to bypass the memo (which would cost one refetch per
 * widget, since these entries are read with ``update: "always"``).
 *
 * A ``WeakMap`` keyed on the model's own map keeps this per-model and lets it
 * die with the model.
 *
 * @type {WeakMap<Map<string, Promise<any>>, Map<string, Set<() => void>>>}
 */
const staleReloadSubscribers = new WeakMap();

/**
 * @param {Map<string, Promise<any>>} specialDataCaches
 * @param {string} key
 * @returns {Set<() => void>}
 */
function subscribersFor(specialDataCaches, key) {
    let byKey = staleReloadSubscribers.get(specialDataCaches);
    if (!byKey) {
        byKey = new Map();
        staleReloadSubscribers.set(specialDataCaches, byKey);
    }
    let subscribers = byKey.get(key);
    if (!subscribers) {
        subscribers = new Set();
        byKey.set(key, subscribers);
    }
    return subscribers;
}

/**
 * Hook for loading and caching special data (e.g. selection options) tied to a
 * record's lifecycle. Uses ORM disk cache with change detection to keep the
 * data fresh across record navigation.
 *
 * @template T, [Props=any]
 * @param {(orm: Services["orm"], props: Component<Props>["props"]) => Promise<T>} loadFn
 * @returns {{ data: T }}
 */
export function useSpecialData(loadFn) {
    const component = useComponent();
    const record = component.props.record;
    const { specialDataCaches } = record.model;
    const orm = component.env.services.orm;
    let loadTicket = 0;
    let appliedTicket = 0;
    const apply = (ticket, data) => {
        if (ticket >= appliedTicket) {
            appliedTicket = ticket;
            result.data = data;
        }
    };
    // Function declaration, not a const: it and `ormWithCache` reference each
    // other, and only this direction can be hoisted.
    function reloadOnStaleCache() {
        if (status(component) === "destroyed") {
            return;
        }
        const ticket = ++loadTicket;
        loadFn(ormWithCache, component.props).then((res) => apply(ticket, res));
    }

    /** Subscriber sets this hook joined, so it can leave every one on destroy. */
    const joinedSubscribers = new Set();
    onWillDestroy(() => {
        for (const subscribers of joinedSubscribers) {
            subscribers.delete(reloadOnStaleCache);
        }
        joinedSubscribers.clear();
    });

    const ormWithCache = Object.create(orm);
    ormWithCache.call = (...args) => {
        const key = JSON.stringify(args);
        const subscribers = subscribersFor(specialDataCaches, key);
        subscribers.add(reloadOnStaleCache);
        joinedSubscribers.add(subscribers);
        if (!specialDataCaches.has(key)) {
            const prom = orm
                .cache({
                    type: "disk",
                    update: "always",
                    callback: (res, hasChanged) => {
                        specialDataCaches.set(key, Promise.resolve(res));
                        if (!hasChanged) {
                            return;
                        }
                        // Snapshot: a subscriber may unsubscribe (destroy)
                        // while the loop runs.
                        for (const subscriber of [...subscribers]) {
                            subscriber();
                        }
                    },
                })
                .call(...args);
            specialDataCaches.set(key, prom);
            prom.catch(() => {
                if (specialDataCaches.get(key) === prom) {
                    specialDataCaches.delete(key);
                }
            });
        }
        return specialDataCaches.get(key);
    };

    /** @type {{ data: T }} */
    const result = useState(/** @type {any} */ ({ data: {} }));
    useRecordObserver(async (record, props) => {
        const ticket = ++loadTicket;
        apply(ticket, await loadFn(ormWithCache, { ...props, record }));
    });
    onWillUpdateProps(async (props) => {
        if (props.record.id === component.props.record.id) {
            const ticket = ++loadTicket;
            apply(ticket, await loadFn(ormWithCache, props));
        }
    });
    return result;
}
