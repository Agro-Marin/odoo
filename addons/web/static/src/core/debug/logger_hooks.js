// @ts-check
/** @odoo-module native */

import {
    onMounted,
    onPatched,
    onRendered,
    onWillDestroy,
    onWillPatch,
    onWillRender,
    onWillUnmount,
    useComponent,
} from "@odoo/owl";

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
    const component = /** @type {any} */ (useComponent());
    const tag = name || component.constructor.name;
    const createdAt = performance.now();
    let renderedAt = 0;
    let patchedAt = 0;
    let renders = 0;
    let patches = 0;
    log.lifecycle(`${tag} setup`, () => component.props);
    onWillRender(() => {
        renders++;
        renderedAt = performance.now();
    });
    onRendered(() => {
        if (log.isEnabled("perf")) {
            const ms = performance.now() - renderedAt;
            log.perf(`${tag} render#${renders}`)({ ms: Number(ms.toFixed(2)) });
        }
    });
    onMounted(() => {
        log.lifecycle(`${tag} mounted`, () => ({
            sinceSetupMs: Number((performance.now() - createdAt).toFixed(2)),
        }));
    });
    onWillPatch(() => {
        patches++;
        patchedAt = performance.now();
        log.lifecycle(`${tag} willPatch#${patches}`, () => component.props);
    });
    onPatched(() => {
        log.lifecycle(`${tag} patched#${patches}`, () => ({
            ms: Number((performance.now() - patchedAt).toFixed(2)),
        }));
    });
    onWillUnmount(() =>
        log.lifecycle(`${tag} willUnmount`, () => ({ renders, patches })),
    );
    onWillDestroy(() => log.lifecycle(`${tag} willDestroy`));
}
