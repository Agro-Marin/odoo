// @ts-check
/** @odoo-module native */

import { onWillDestroy, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";
import { uniqueId } from "@web/core/utils/functions";
import { useProps } from "@web/core/utils/props";
import { effect } from "@web/core/utils/reactive";
import { batched } from "@web/core/utils/timing";

/** @param {(record: any, props?: any) => void | Promise<void>} callback */
export function useRecordObserver(callback) {
    const componentProps = useProps();
    let currentId;
    let disposeEffect;
    let latestProps = componentProps;
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
        let settled = false;
        const runCallback = (record) =>
            Promise.resolve(callback(record, latestProps)).then(
                (result) => {
                    settled = true;
                    def.resolve(result);
                },
                (error) => {
                    if (!settled) {
                        settled = true;
                        def.reject(error);
                        return;
                    }
                    console.error(
                        "[useRecordObserver] callback failed after the initial " +
                            "call; the error cannot be surfaced through the " +
                            "component lifecycle and was swallowed:",
                        error,
                    );
                },
            );
        const batchedCallback = batched(
            (record) => {
                if (effectId !== currentId) {
                    return;
                }
                return runCallback(record);
            },
            () =>
                new Promise((resolve) =>
                    browser.requestAnimationFrame(() => resolve()),
                ),
        );
        disposeEffect = effect(
            (record) => {
                if (firstCall) {
                    firstCall = false;
                    return runCallback(record);
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
        latestProps = componentProps;
        await observeRecord(componentProps);
    });
    onWillUpdateProps(async (nextProps) => {
        latestProps = nextProps;
        if (nextProps.record !== componentProps.record) {
            await observeRecord(nextProps);
        }
    });
}
