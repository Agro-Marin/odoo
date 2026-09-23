// @ts-check
/** @odoo-module native */

import {
    onMounted,
    onPatched,
    onWillDestroy,
    onWillPatch,
    onWillUnmount,
} from "@odoo/owl";
import { useComponentName, useProps } from "@web/core/utils/owl_bridge";

/** @typedef {import("./debug_logger").DebugLogger} DebugLogger */

/**
 * Owl awaits `Promise.all(willStart)` and `Promise.all(willUpdateProps)`
 * whether or not a handler is registered, and `Promise.all([undefined])`
 * settles later than `Promise.all([])`: registering either hook delays every
 * mount and props update by a few microtasks. A lifecycle logger must not
 * move timing, so those two hooks are deliberately absent -- the time to
 * mount is reported from setup at `mounted` instead.
 *
 * @param {DebugLogger} log
 * @param {string} [name]
 */
export function useLifecycleLog(log, name) {
    const props = useProps();
    const componentName = useComponentName();
    const tag = name || componentName;
    const createdAt = performance.now();
    let patches = 0;
    /** @type {import("./debug_logger").PerfEnd} */
    let endPatch = () => 0;
    log.lifecycle(`${tag} setup`, () => props);
    onMounted(() => {
        log.lifecycle(`${tag} mounted`, () => ({
            sinceSetupMs: Number((performance.now() - createdAt).toFixed(2)),
        }));
    });
    onWillPatch(() => {
        patches++;
        log.lifecycle(`${tag} willPatch#${patches}`, () => props);
        endPatch = log.perf(`${tag} patch`, { n: patches });
    });
    onPatched(() => {
        endPatch();
        log.lifecycle(`${tag} patched#${patches}`);
    });
    onWillUnmount(() =>
        log.lifecycle(`${tag} willUnmount`, () => ({ renders: patches + 1, patches })),
    );
    onWillDestroy(() => log.lifecycle(`${tag} willDestroy`));
}
