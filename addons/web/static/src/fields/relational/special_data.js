// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/special_data - OWL hook for loading and caching special data tied to a record lifecycle */

import { onWillUpdateProps, status, useComponent, useState } from "@odoo/owl";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
/** @import { Component } from "@odoo/owl" */
/** @import { Services } from "services" */

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
    // Guard ``result.data`` against out-of-order loads across all three paths
    // (the record-observer effect, onWillUpdateProps, and the cache "changed"
    // callback below): a slower earlier load must not clobber a newer one.
    // Each load takes a monotonic ticket and writes only if no newer load has
    // already written. This is deliberately NOT a KeepLast: KeepLast abandons a
    // superseded promise outright, so the first valid result would be dropped
    // and the update forced to wait for a later refetch — a visible render lag
    // (e.g. a dynamic-domain status bar not reflecting a re-fetch in time).
    let loadTicket = 0;
    let appliedTicket = 0;
    const apply = (ticket, data) => {
        if (ticket >= appliedTicket) {
            appliedTicket = ticket;
            result.data = data;
        }
    };
    const ormWithCache = Object.create(orm);
    ormWithCache.call = (...args) => {
        const key = JSON.stringify(args);
        if (!specialDataCaches[key]) {
            // Store the in-flight promise synchronously so concurrent first
            // calls share it instead of re-entering the RPC cache layer.
            const prom = orm
                .cache({
                    type: "disk",
                    update: "always",
                    callback: (res, hasChanged) => {
                        specialDataCaches[key] = Promise.resolve(res);
                        if (status(component) !== "destroyed" && hasChanged) {
                            const ticket = ++loadTicket;
                            loadFn(ormWithCache, component.props).then((res) =>
                                apply(ticket, res),
                            );
                        }
                    },
                })
                .call(...args);
            specialDataCaches[key] = prom;
            prom.catch(() => {
                // Do not cache failures: the next call must retry.
                if (specialDataCaches[key] === prom) {
                    delete specialDataCaches[key];
                }
            });
        }
        return specialDataCaches[key];
    };

    /** @type {{ data: T }} */
    const result = useState(/** @type {any} */ ({ data: {} }));
    useRecordObserver(async (record, props) => {
        const ticket = ++loadTicket;
        apply(ticket, await loadFn(ormWithCache, { ...props, record }));
    });
    onWillUpdateProps(async (props) => {
        // useRecordObserver callback is not called when the record doesn't change
        if (props.record.id === component.props.record.id) {
            const ticket = ++loadTicket;
            apply(ticket, await loadFn(ormWithCache, props));
        }
    });
    return result;
}
