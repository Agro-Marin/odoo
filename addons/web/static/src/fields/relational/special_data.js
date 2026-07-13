// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/special_data - OWL hook for loading and caching special data tied to a record lifecycle */

import { onWillUpdateProps, status, useComponent, useState } from "@odoo/owl";
import { KeepLast } from "@web/core/utils/concurrency";
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
    // Every path that writes `result.data` goes through this KeepLast so that
    // out-of-order RPC resolution can never leave stale option data: when the
    // effective domain/context changes, each loadFn produces a distinct cache
    // key (JSON.stringify) and thus an independent in-flight RPC, so only the
    // most recently initiated load may win the assignment.
    const keepLast = new KeepLast();
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
                            keepLast
                                .add(loadFn(ormWithCache, component.props))
                                .then((res) => {
                                    result.data = res;
                                });
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
        result.data = await keepLast.add(loadFn(ormWithCache, { ...props, record }));
    });
    onWillUpdateProps(async (props) => {
        // useRecordObserver callback is not called when the record doesn't change
        if (props.record.id === component.props.record.id) {
            result.data = await keepLast.add(loadFn(ormWithCache, props));
        }
    });
    return result;
}
