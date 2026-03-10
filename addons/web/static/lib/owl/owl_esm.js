/** @odoo-module */
/**
 * ESM bridge for OWL — re-exports the UMD global as ES module named exports.
 *
 * This file is referenced by the import map as "@odoo/owl". It runs AFTER
 * the legacy bundle (which loads owl.js UMD and sets globalThis.owl),
 * because the bridge <script type="module"> is placed after the deferred
 * bundle in document order.
 */

const _owl = globalThis.owl;

export const {
    App,
    Component,
    EventBus,
    OwlError,
    __info__,
    batched,
    blockDom,
    htmlEscape,
    loadFile,
    markRaw,
    markup,
    mount,
    onError,
    onMounted,
    onPatched,
    onRendered,
    onWillDestroy,
    onWillPatch,
    onWillRender,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    reactive,
    status,
    toRaw,
    useChildSubEnv,
    useComponent,
    useEffect,
    useEnv,
    useExternalListener,
    useRef,
    useState,
    useSubEnv,
    validate,
    validateType,
    whenReady,
    xml,
} = _owl;

export default _owl;
