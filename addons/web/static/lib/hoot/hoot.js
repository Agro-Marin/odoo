/** @odoo-module alias=@odoo/hoot default=false */

import { logger } from "./core/logger.js";
import { Runner } from "./core/runner.js";
import { urlParams } from "./core/url.js";
import { copyAndBind, makeRuntimeHook } from "./hoot_utils.js";
import { setRunner } from "./main_runner.js";
import { setupHootUI } from "./ui/setup_hoot_ui.js";

/**
 * @typedef {import("../hoot-dom/helpers/dom").Dimensions} Dimensions
 * @typedef {import("../hoot-dom/helpers/dom").FormatXmlOptions} FormatXmlOptions
 * @typedef {import("../hoot-dom/helpers/dom").Position} Position
 * @typedef {import("../hoot-dom/helpers/dom").QueryOptions} QueryOptions
 * @typedef {import("../hoot-dom/helpers/dom").QueryRectOptions} QueryRectOptions
 * @typedef {import("../hoot-dom/helpers/dom").QueryTextOptions} QueryTextOptions
 * @typedef {import("../hoot-dom/helpers/dom").Target} Target
 *
 * @typedef {import("../hoot-dom/helpers/events").DragHelpers} DragHelpers
 * @typedef {import("../hoot-dom/helpers/events").DragOptions} DragOptions
 * @typedef {import("../hoot-dom/helpers/events").EventType} EventType
 * @typedef {import("../hoot-dom/helpers/events").FillOptions} FillOptions
 * @typedef {import("../hoot-dom/helpers/events").InputValue} InputValue
 * @typedef {import("../hoot-dom/helpers/events").KeyStrokes} KeyStrokes
 * @typedef {import("../hoot-dom/helpers/events").PointerOptions} PointerOptions
 *
 * @typedef {import("./mock/network").ServerWebSocket} ServerWebSocket
 *
 * @typedef {{
 *  runner: Runner;
 *  ui: import("./ui/setup_hoot_ui").UiState
 * }} Environment
 */

//-----------------------------------------------------------------------------
// Internal
//-----------------------------------------------------------------------------

const runner = new Runner(urlParams);

setRunner(runner);

//-----------------------------------------------------------------------------
// Exports
//-----------------------------------------------------------------------------

// Main test API
export const describe = runner.describe;
export const expect = runner.expect;
export const test = runner.test;

// Test hooks
export const after = makeRuntimeHook("after");
export const afterEach = makeRuntimeHook("afterEach");
export const before = makeRuntimeHook("before");
export const beforeEach = makeRuntimeHook("beforeEach");
export const onError = makeRuntimeHook("onError");

// Fixture
export const getFixture = runner.fixture.get;

// Other test runner functions
export const definePreset = runner.exportFn(runner.definePreset);
export const dryRun = runner.exportFn(runner.dryRun);
export const getCurrent = runner.exportFn(runner.getCurrent);
export const start = runner.exportFn(runner.start);
export const stop = runner.exportFn(runner.stop);

export { makeExpect } from "./core/expect.js";
export { destroy } from "./core/fixture.js";
export { defineTags } from "./core/tag.js";
export { createJobScopedGetter } from "./hoot_utils.js";

// Constants
export const globals = copyAndBind(globalThis);
// Only auto-mount the Hoot UI on the dedicated test runner page.
// The bridge script of every ESM bundle imports @odoo/hoot to register
// it in odoo.loader.modules, which used to be harmless because the
// esbuild shim did not execute the real module body. After the ESM
// native migration (and the fix that makes the import map resolve
// @odoo/hoot to the real hoot.js URL instead of a shim), this
// side-effect fires on every page — including the webclient —
// overlaying the test runner UI on top of the actual app. Gate the
// call so the UI only appears when the page explicitly requested it.
//
// Two distinct pages legitimately host Hoot and need both the UI AND the
// global API mocks (patchWindow): the integrated Odoo JS runner at
// /web/tests, and the standalone Hoot self-test harness served from
// /web/static/lib/hoot/tests/. The latter was wrongly excluded by a
// /web/tests-only check, leaving its mock-dependent suites (network,
// timers, navigator) running against the real browser APIs.
const _inTestPage = typeof window !== "undefined"
    && (window.location.pathname.startsWith("/web/tests")
        || window.location.pathname.startsWith("/web/static/lib/hoot/tests/"));
export const isHootReady = _inTestPage ? setupHootUI() : Promise.resolve();

// Mock
export { disableAnimations, enableTransitions } from "./mock/animation.js";
export { mockDate, mockLocale, mockTimeZone, onTimeZoneChange } from "./mock/date.js";
export { makeSeededRandom } from "./mock/math.js";
export { mockPermission, mockSendBeacon, mockUserAgent, mockVibrate } from "./mock/navigator.js";
export {
    mockFetch,
    mockHistory,
    mockLocation,
    mockWebSocket,
    mockWorker,
    withFetch,
} from "./mock/network.js";
export { flushNotifications } from "./mock/notification.js";
export {
    mockMatchMedia,
    mockTouch,
    watchAddedNodes,
    watchKeys,
    watchListeners,
} from "./mock/window.js";

// HOOT-DOM
export {
    advanceFrame,
    advanceTime,
    animationFrame,
    cancelAllTimers,
    check,
    clear,
    click,
    dblclick,
    Deferred,
    delay,
    drag,
    edit,
    fill,
    formatXml,
    freezeTime,
    getActiveElement,
    getFocusableElements,
    getNextFocusableElement,
    getParentFrame,
    getPreviousFocusableElement,
    hover,
    isDisplayed,
    isEditable,
    isFocusable,
    isInDOM,
    isInViewPort,
    isScrollable,
    isVisible,
    keyDown,
    keyUp,
    leave,
    manuallyDispatchProgrammaticEvent,
    matches,
    microTick,
    middleClick,
    observe,
    on,
    pointerDown,
    pointerUp,
    press,
    queryAll,
    queryAllAttributes,
    queryAllProperties,
    queryAllRects,
    queryAllTexts,
    queryAllValues,
    queryAny,
    queryAttribute,
    queryFirst,
    queryOne,
    queryRect,
    queryText,
    queryValue,
    resize,
    rightClick,
    runAllTimers,
    scroll,
    select,
    setFrameRate,
    setInputFiles,
    setInputRange,
    tick,
    uncheck,
    unfreezeTime,
    unload,
    waitFor,
    waitForNone,
    waitUntil,
} from "@odoo/hoot-dom";

// Debug
export { exposeHelpers } from "../hoot-dom/hoot_dom_utils.js";
export const __debug__ = runner;

/**
 * @param {...unknown} values
 */
export function registerDebugInfo(...values) {
    logger.logDebug(...values);
}
