// @ts-check
/** @odoo-module native */

/** @module @web/fields/hooks/record_observer - OWL hook for observing record value changes in field components */

import { onWillDestroy, onWillStart, onWillUpdateProps, useComponent } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";
import { uniqueId } from "@web/core/utils/functions";
import { disposableEffect } from "@web/core/utils/reactive";
import { batched } from "@web/core/utils/timing";

/**
 * Use only in a component field (depends on record props). Runs once at
 * setup and again whenever a record value read in the callback changes.
 * @param {(record: any, props?: any) => void | Promise<void>} callback
 */
export function useRecordObserver(callback) {
    const component = useComponent();
    let currentId;
    // Disposer for the active effect. Disposed on each record swap and on
    // teardown so a superseded effect stops firing (no wasted batched rAF).
    let disposeEffect;
    const observeRecord = (props) => {
        currentId = uniqueId();
        disposeEffect?.();
        disposeEffect = undefined;
        if (!props.record) {
            return;
        }
        const def = new Deferred();
        const effectId = currentId;
        let firstCall = true;
        // Coalesce all effect notifications within one animation frame.
        const batchedCallback = batched(
            (record) => {
                if (effectId !== currentId) {
                    // disposableEffect doesn't clean up on unmount; guard manually.
                    return;
                }
                return Promise.resolve(callback(record, props))
                    .then(def.resolve)
                    .catch(def.reject);
            },
            () =>
                new Promise((resolve) =>
                    browser.requestAnimationFrame(() => resolve()),
                ),
        );
        disposeEffect = disposableEffect(
            (record) => {
                if (firstCall) {
                    firstCall = false;
                    return Promise.resolve(callback(record, props))
                        .then(def.resolve)
                        .catch(def.reject);
                } else {
                    return batchedCallback(record);
                }
            },
            [props.record],
        );
        return def;
    };
    onWillDestroy(() => {
        currentId = uniqueId();
        disposeEffect?.();
        disposeEffect = undefined;
    });
    onWillStart(async () => {
        await observeRecord(component.props);
    });
    onWillUpdateProps(async (nextProps) => {
        if (nextProps.record !== component.props.record) {
            await observeRecord(nextProps);
        }
    });
}
