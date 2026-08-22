/** @odoo-module alias=@odoo/hoot-dom default=false */

import * as dom from "@odoo/hoot-dom-helpers-dom";
import * as events from "@odoo/hoot-dom-helpers-events";
import * as time from "@odoo/hoot-dom-helpers-time";
import { interactor } from "@odoo/hoot-dom-utils";

/**
 * @typedef {import("./helpers/dom").Dimensions} Dimensions
 * @typedef {import("./helpers/dom").FormatXmlOptions} FormatXmlOptions
 * @typedef {import("./helpers/dom").Position} Position
 * @typedef {import("./helpers/dom").QueryOptions} QueryOptions
 * @typedef {import("./helpers/dom").QueryRectOptions} QueryRectOptions
 * @typedef {import("./helpers/dom").QueryTextOptions} QueryTextOptions
 * @typedef {import("./helpers/dom").Target} Target
 *
 * @typedef {import("./helpers/events").DragHelpers} DragHelpers
 * @typedef {import("./helpers/events").DragOptions} DragOptions
 * @typedef {import("./helpers/events").EventType} EventType
 * @typedef {import("./helpers/events").FillOptions} FillOptions
 * @typedef {import("./helpers/events").InputValue} InputValue
 * @typedef {import("./helpers/events").KeyStrokes} KeyStrokes
 * @typedef {import("./helpers/events").PointerOptions} PointerOptions
 */

export {
    formatXml,
    getActiveElement,
    getFocusableElements,
    getNextFocusableElement,
    getParentFrame,
    getPreviousFocusableElement,
    isDisplayed,
    isEditable,
    isFocusable,
    isInDOM,
    isInViewPort,
    isScrollable,
    isVisible,
    matches,
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
} from "@odoo/hoot-dom-helpers-dom";
export { on } from "@odoo/hoot-dom-helpers-events";
export {
    animationFrame,
    cancelAllTimers,
    Deferred,
    delay,
    freezeTime,
    unfreezeTime,
    microTick,
    setFrameRate,
    tick,
    waitUntil,
} from "@odoo/hoot-dom-helpers-time";

export const observe = interactor("query", dom.observe);
export const waitFor = interactor("query", dom.waitFor);
export const waitForNone = interactor("query", dom.waitForNone);

export const check = interactor("interaction", events.check);
export const clear = interactor("interaction", events.clear);
export const click = interactor("interaction", events.click);
export const dblclick = interactor("interaction", events.dblclick);
export const drag = interactor("interaction", events.drag);
export const edit = interactor("interaction", events.edit);
export const fill = interactor("interaction", events.fill);
export const hover = interactor("interaction", events.hover);
export const keyDown = interactor("interaction", events.keyDown);
export const keyUp = interactor("interaction", events.keyUp);
export const leave = interactor("interaction", events.leave);
export const manuallyDispatchProgrammaticEvent = interactor("interaction", events.dispatch);
export const middleClick = interactor("interaction", events.middleClick);
export const pointerDown = interactor("interaction", events.pointerDown);
export const pointerUp = interactor("interaction", events.pointerUp);
export const press = interactor("interaction", events.press);
export const resize = interactor("interaction", events.resize);
export const rightClick = interactor("interaction", events.rightClick);
export const scroll = interactor("interaction", events.scroll);
export const select = interactor("interaction", events.select);
export const setInputFiles = interactor("interaction", events.setInputFiles);
export const setInputRange = interactor("interaction", events.setInputRange);
export const uncheck = interactor("interaction", events.uncheck);
export const unload = interactor("interaction", events.unload);

export const advanceFrame = interactor("time", time.advanceFrame);
export const advanceTime = interactor("time", time.advanceTime);
export const runAllTimers = interactor("time", time.runAllTimers);

export { exposeHelpers } from "@odoo/hoot-dom-utils";

import { exposeHelpers } from "@odoo/hoot-dom-utils";
export default { ...dom, ...events, ...time,
    observe, waitFor, waitForNone,
    check, clear, click, dblclick, drag, edit, fill, hover,
    keyDown, keyUp, leave, manuallyDispatchProgrammaticEvent, middleClick,
    pointerDown, pointerUp, press, resize, rightClick, scroll, select,
    setInputFiles, setInputRange, uncheck, unload,
    advanceFrame, advanceTime, runAllTimers,
    exposeHelpers,
};
