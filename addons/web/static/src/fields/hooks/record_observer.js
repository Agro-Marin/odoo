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
 *
 * The effect is re-armed on record *identity* changes only, but the ``props``
 * given to the callback are always the component's latest props: prop-only
 * updates (readonly/domain/context/...) refresh the reference read at call
 * time instead of leaving the callback with the snapshot captured when the
 * effect was armed. Callbacks fired asynchronously (batched on an animation
 * frame) therefore never observe stale non-record props.
 * @param {(record: any, props?: any) => void | Promise<void>} callback
 */
export function useRecordObserver(callback) {
    const component = useComponent();
    let currentId;
    // Disposer for the active effect. Disposed on each record swap and on
    // teardown so a superseded effect stops firing (no wasted batched rAF).
    let disposeEffect;
    // Latest props received by the component; the callback invocations below
    // read this at call time rather than capturing `observeRecord`'s argument.
    let latestProps = component.props;
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
                return Promise.resolve(callback(record, latestProps))
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
                    return Promise.resolve(callback(record, latestProps))
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
        latestProps = component.props;
        await observeRecord(component.props);
    });
    onWillUpdateProps(async (nextProps) => {
        // Always refresh the props reference — even on a prop-only update —
        // so pending/future callback invocations see the fresh props; only a
        // record identity change requires re-arming the effect (and firing
        // the callback) since the reactive subscriptions target the record.
        latestProps = nextProps;
        if (nextProps.record !== component.props.record) {
            await observeRecord(nextProps);
        }
    });
}
