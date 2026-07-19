// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dnd/draggable_hook_builder - Factory for configurable drag-and-drop OWL hooks with touch and scroll support */

import { browser } from "@web/core/browser/browser";
import { hasTouch, isBrowserFirefox, isIOS } from "@web/core/browser/feature_detection";
import { omit } from "@web/core/utils/collections/objects";
import { clamp } from "@web/core/utils/format/numbers";
import { setRecurringAnimationFrame } from "@web/core/utils/timing";

import {
    DEFAULT_ACCEPTED_PARAMS,
    DEFAULT_DEFAULT_PARAMS,
    DRAGGED_CLASS,
    getReturnValue,
    getScrollParents,
    LEFT_CLICK,
    makeCleanupManager,
    makeDOMHelpers,
    MANDATORY_PARAMS,
    safePrevent,
    toFunction,
    WHITE_LISTED_KEYS,
} from "./draggable_hook_builder_utils.js";

export { DRAGGED_CLASS };

/**
 * @typedef {ReturnType<typeof makeCleanupManager>} CleanupManager
 *
 * @typedef {ReturnType<typeof makeDOMHelpers>} DOMHelpers
 *
 * @typedef DraggableBuilderParams
 * Hook params
 * @property {string} [name="useAnonymousDraggable"]
 * @property {EdgeScrollingOptions} [edgeScrolling]
 * @property {Record<string, string[]>} [acceptedParams]
 * @property {Record<string, any>} [defaultParams]
 * Setup hooks
 * @property {{
 *  addListener?: typeof import("@odoo/owl")["useExternalListener"];
 *  setup: typeof import("@odoo/owl")["useEffect"];
 *  teardown: typeof import("@odoo/owl")["onWillUnmount"];
 *  throttle: typeof import("@web/core/utils/timing")["useThrottleForAnimation"];
 *  wrapState: typeof import("@odoo/owl")["reactive"];
 * }} setupHooks
 * Build hooks
 * @property {(params: DraggableBuildHandlerParams) => any} onComputeParams
 * Runtime hooks
 * @property {(params: DraggableBuildHandlerParams) => any} onDragStart
 * @property {(params: DraggableBuildHandlerParams) => any} onDrag
 * @property {(params: DraggableBuildHandlerParams) => any} onDragEnd
 * @property {(params: DraggableBuildHandlerParams) => any} onDrop
 * @property {(params: DraggableBuildHandlerParams) => any} onWillStartDrag
 *
 * @typedef {{
 *  ref: { el: HTMLElement | null };
 *  elementSelector?: string | null;
 *  ignoreSelector?: string | null;
 *  fullSelector?: string | null;
 *  followCursor?: boolean;
 *  cursor?: string | null;
 *  enable?: () => boolean;
 *  preventDrag?: (el: HTMLElement) => boolean;
 *  pointer?: Position;
 *  edgeScrolling?: EdgeScrollingOptions;
 *  delay?: number;
 *  tolerance?: number;
 *  touchDelay?: number;
 *  dragging?: boolean;
 *  willDrag?: boolean;
 *  current: DraggableHookCurrentContext;
 *  [key: string]: any;
 * }} DraggableHookContext
 *
 * @typedef {{
 *  container?: HTMLElement;
 *  containerRect?: DOMRect;
 *  element?: HTMLElement;
 *  elementRect?: DOMRect;
 *  scrollParentX?: HTMLElement | null;
 *  scrollParentXRect?: DOMRect | null;
 *  scrollParentY?: HTMLElement | null;
 *  scrollParentYRect?: DOMRect | null;
 *  timeout?: number;
 *  initialPosition?: Position;
 *  offset?: Position;
 *  [key: string]: any;
 * }} DraggableHookCurrentContext
 *
 * @typedef EdgeScrollingOptions
 * @property {boolean} [enabled=true]
 * @property {number} [speed=10]
 * @property {number} [threshold=20]
 * @property {"horizontal"|"vertical"} [direction]
 *
 * @typedef Position
 * @property {number} x
 * @property {number} y
 *
 * @typedef {DOMHelpers & {
 *  ctx: DraggableHookContext,
 *  addCleanup(cleanupFn: () => any): void,
 *  addEffectCleanup(cleanupFn: () => any): void,
 *  callHandler(handlerName: string, arg: Record<any, any>): void,
 * }} DraggableBuildHandlerParams
 *
 * @typedef {DOMHelpers & Position & { element: HTMLElement }} DraggableHandlerParams
 */

/**
 * @param {DraggableBuilderParams} hookParams
 * @returns {(params: Record<keyof typeof DEFAULT_ACCEPTED_PARAMS, any>) => { dragging: boolean }}
 */
export function makeDraggableHook(hookParams) {
    hookParams = getReturnValue(hookParams);

    const hookName = hookParams.name || "useAnonymousDraggable";
    const { setupHooks } = hookParams;
    /** @type {Record<string, any[]>} */
    const allAcceptedParams = {
        ...DEFAULT_ACCEPTED_PARAMS,
        ...hookParams.acceptedParams,
    };
    /** @type {Record<string, any>} */
    const defaultParams = {
        ...DEFAULT_DEFAULT_PARAMS,
        ...hookParams.defaultParams,
    };

    // Stable key order for the param-merge effect dependencies below.
    const paramKeys = Object.keys(allAcceptedParams);

    /**
     * Computes the current param values, in `paramKeys` order. Must return a
     * flat array of stable values: owl's `useEffect` compares deps with
     * `!==`, so a fresh wrapper here (e.g. `toFunction(enable)`) would make
     * every dep differ each render, re-running the effect for all consumers
     * on every patch. `enable` is wrapped with `toFunction` in the effect
     * body instead, not here.
     *
     * @param {Record<string, any>} params
     * @returns {any[]}
     */
    const computeParams = (params) =>
        paramKeys.map((prop) => {
            if (!(prop in params)) {
                return undefined;
            }
            if (
                prop === "enable" ||
                (allAcceptedParams[prop].length === 1 &&
                    allAcceptedParams[prop][0] === Function)
            ) {
                return params[prop];
            }
            return getReturnValue(params[prop]);
        });

    /**
     * Basic error builder for the hook.
     * @param {string} reason
     * @returns {Error}
     */
    const makeError = (reason) => new Error(`Error in hook ${hookName}: ${reason}.`);

    return {
        [hookName](/** @type {Record<string, any>} */ params) {
            let preventClick = false;
            /**
             * Executes a handler from the `hookParams`.
             * @param {string} hookHandlerName
             * @param {Record<any, any>} [arg]
             */
            const callBuildHandler = (hookHandlerName, arg = {}) => {
                if (
                    typeof (
                        /** @type {Record<string, any>} */ (hookParams)[hookHandlerName]
                    ) !== "function"
                ) {
                    return;
                }
                const returnValue = /** @type {Record<string, any>} */ (hookParams)[
                    hookHandlerName
                ]({
                    ctx,
                    ...helpers,
                    ...arg,
                });
                if (returnValue) {
                    callHandler(hookHandlerName, returnValue);
                }
            };

            /**
             * Safely executes a handler from the `params`, so that the drag sequence can
             * be interrupted if an error occurs.
             * @param {string} handlerName
             * @param {Record<any, any>} arg
             */
            const callHandler = (handlerName, arg) => {
                if (typeof params[handlerName] !== "function") {
                    return;
                }
                try {
                    params[handlerName]({ ...dom, ...ctx.pointer, ...arg });
                } catch (err) {
                    dragEnd(null, true);
                    throw err;
                }
            };

            /**
             * Returns whether the user has moved from at least the number of pixels
             * that are tolerated from the initial pointer position.
             */
            const canStartDrag = () => {
                const {
                    pointer,
                    current: { initialPosition },
                } = ctx;
                return (
                    !ctx.tolerance ||
                    Math.hypot(
                        pointer.x - initialPosition.x,
                        pointer.y - initialPosition.y,
                    ) >= ctx.tolerance
                );
            };

            /**
             * Main entry function to start a drag sequence.
             */
            const dragStart = () => {
                state.dragging = true;
                state.willDrag = false;

                // Compute scrollable parent
                const isDocumentScrollingElement =
                    ctx.current.container ===
                    ctx.current.container.ownerDocument.scrollingElement;
                // If the container is the "ownerDocument.scrollingElement",
                // there is no need to get the scroll parent as it is the
                // scrollable element itself.
                // TODO: investigate if "getScrollParents" should not consider
                // the "ownerDocument.scrollingElement" directly.
                [ctx.current.scrollParentX, ctx.current.scrollParentY] =
                    isDocumentScrollingElement
                        ? [ctx.current.container, ctx.current.container]
                        : getScrollParents(ctx.current.container);

                updateRects();
                const { x, y, width, height } = ctx.current.elementRect;

                ctx.current.offset = {
                    x: ctx.current.initialPosition.x - x,
                    y: ctx.current.initialPosition.y - y,
                };

                if (ctx.followCursor) {
                    dom.addStyle(ctx.current.element, {
                        width: `${width}px`,
                        height: `${height}px`,
                        // Limit the impact of width and height !important on the dragged element
                        "max-width": `${width}px`,
                        "max-height": `${height}px`,
                        position: "fixed !important",
                    });

                    // First adjustment
                    updateElementPosition();
                }

                dom.addClass(document.body, "pe-none", "user-select-none");
                if (params.iframeWindow) {
                    for (const iframe of document.getElementsByTagName("iframe")) {
                        if (iframe.contentWindow === params.iframeWindow) {
                            dom.addClass(iframe, "pe-none", "user-select-none");
                        }
                    }
                }
                // FIXME: adding pe-none and cursor on the same element makes
                // no sense as pe-none prevents the cursor to be displayed.
                if (ctx.cursor) {
                    dom.addStyle(document.body, { cursor: ctx.cursor });
                }

                if (
                    (ctx.current.scrollParentX || ctx.current.scrollParentY) &&
                    ctx.edgeScrolling.enabled
                ) {
                    // Rects were computed above (`updateRects`) and are then
                    // only marked for recomputation after an actual scroll or
                    // resize, instead of being recomputed on every animation
                    // frame: `updateRects` interleaves layout reads (rects,
                    // computed styles, scroll sizes) with the same-frame style
                    // writes of the drag sequence, forcing a layout per frame.
                    ctx.current.rectsDirty = false;
                    const markRectsDirty = () => (ctx.current.rectsDirty = true);
                    dom.addListener(window, "resize", markRectsDirty);
                    dom.addListener(
                        /** @type {HTMLElement} */ (ctx.current.container)
                            .ownerDocument,
                        "scroll",
                        markRectsDirty,
                        { capture: true, passive: true },
                    );
                    const cleanupFn = setRecurringAnimationFrame(handleEdgeScrolling);
                    cleanup.add(cleanupFn);
                }

                dom.addClass(ctx.current.element, DRAGGED_CLASS);

                callBuildHandler("onDragStart");
            };

            /**
             * Main exit function to stop a drag sequence: can be called even if a
             * drag sequence did not start yet, to clean up current context variables.
             * @param {HTMLElement | null} target
             * @param {boolean} [inErrorState] can be set to true when an error
             *  occurred to avoid falling into an infinite loop if the error
             *  originated from one of the handlers.
             */
            const dragEnd = (target, inErrorState) => {
                try {
                    if (state.dragging) {
                        preventClick = true;
                        if (!inErrorState) {
                            if (
                                target &&
                                (params.allowDisconnected ||
                                    ctx.current.element.isConnected)
                            ) {
                                callBuildHandler("onDrop", { target });
                            }
                            callBuildHandler("onDragEnd");
                        }
                    }
                } finally {
                    // Teardown is unconditional by construction. `callBuildHandler`
                    // — unlike its guarded sibling `callHandler` — does not catch,
                    // and consumers reach it with their OWN callbacks (e.g.
                    // nested_sortable invokes `params.isAllowed` directly from
                    // `_isAllowedNodeMove`). A throw escaping before this point
                    // left `document.body` carrying `pe-none`/`user-select-none`
                    // and the window pointer/keydown listeners bound, i.e. a page
                    // that stays unclickable for the rest of the session.
                    cleanup.cleanup();
                }
            };

            /**
             * Applies scroll to the container if the current element is near
             * the edge of the container.
             */
            const handleEdgeScrolling = (/** @type {number} */ deltaTime) => {
                // Rects are only recomputed after an actual scroll or resize
                // (marked by the listeners added in `dragStart`), never on
                // idle frames.
                const wereRectsDirty = ctx.current.rectsDirty;
                if (wereRectsDirty) {
                    ctx.current.rectsDirty = false;
                    updateRects();
                }
                const { x: pointerX, y: pointerY } = ctx.pointer;
                const xRect = ctx.current.scrollParentXRect;
                const yRect = ctx.current.scrollParentYRect;

                const { direction, speed, threshold } = ctx.edgeScrolling;

                /** @type {{ x?: [number, number], y?: [number, number] }} */
                const diff = {};
                if (xRect) {
                    const maxWidth = xRect.x + xRect.width;
                    if (pointerX - xRect.x < threshold) {
                        diff.x = [pointerX - xRect.x, -1];
                    } else if (maxWidth - pointerX < threshold) {
                        diff.x = [maxWidth - pointerX, 1];
                    }
                }
                if (yRect) {
                    // "getBoundingClientRect()"" (used in "getRect()") gives the
                    // distance from the element's top to the viewport, excluding
                    // scroll position. Only the "document.scrollingElement" element
                    // ("<html>") accounts for scrollTop. The adjustment is applied
                    // on a local value: the cached rect must not be mutated.
                    let yRectY = yRect.y;
                    const scrollParentYEl = /** @type {HTMLElement} */ (
                        ctx.current.scrollParentY
                    );
                    if (
                        scrollParentYEl ===
                        ctx.current.container.ownerDocument.scrollingElement
                    ) {
                        yRectY += scrollParentYEl.scrollTop;
                    }
                    const maxHeight = yRectY + yRect.height;
                    if (pointerY - yRectY < threshold) {
                        diff.y = [pointerY - yRectY, -1];
                    } else if (maxHeight - pointerY < threshold) {
                        diff.y = [maxHeight - pointerY, 1];
                    }
                }

                let scrolled = false;
                if (diff.x || diff.y) {
                    const correctedSpeed = (speed / 16) * deltaTime;
                    const diffToScroll = (
                        /** @type {[number, number]} */ [delta, sign],
                    ) => (1 - Math.max(delta, 0) / threshold) * correctedSpeed * sign;
                    if ((!direction || direction === "vertical") && diff.y) {
                        const scrollParentY = /** @type {HTMLElement} */ (
                            ctx.current.scrollParentY
                        );
                        const previousScrollTop = scrollParentY.scrollTop;
                        scrollParentY.scrollBy({ top: diffToScroll(diff.y) });
                        scrolled ||= scrollParentY.scrollTop !== previousScrollTop;
                    }
                    if ((!direction || direction === "horizontal") && diff.x) {
                        const scrollParentX = /** @type {HTMLElement} */ (
                            ctx.current.scrollParentX
                        );
                        const previousScrollLeft = scrollParentX.scrollLeft;
                        scrollParentX.scrollBy({ left: diffToScroll(diff.x) });
                        scrolled ||= scrollParentX.scrollLeft !== previousScrollLeft;
                    }
                    if (scrolled) {
                        // Rects moved along with the scrolled content.
                        ctx.current.rectsDirty = true;
                    }
                }
                // Only dispatch "onDrag" on frames where something actually
                // moved under the pointer (edge scroll, or an observed scroll/
                // resize): pointer-driven movement already dispatches "onDrag"
                // from the "pointermove" handler.
                if (scrolled || wereRectsDirty) {
                    callBuildHandler("onDrag");
                }
            };

            /**
             * Global (= ref) "click" event handler.
             * Used to prevent click events after dragEnd
             * @param {PointerEvent} ev
             */
            const onClick = (ev) => {
                if (preventClick) {
                    safePrevent(ev, { stop: true });
                }
            };

            /**
             * Window "keydown" event handler.
             * @param {KeyboardEvent} ev
             */
            const onKeyDown = (ev) => {
                if (!state.dragging || !ctx.enable()) {
                    return;
                }
                if (!WHITE_LISTED_KEYS.includes(ev.key)) {
                    safePrevent(ev, { stop: true });

                    // Cancels drag sequences on every non-whitelisted key down event.
                    dragEnd(null);
                }
            };

            /**
             * Global (= ref) "pointercancel" event handler.
             */
            const onPointerCancel = () => {
                dragEnd(null);
            };

            /**
             * Global (= ref) "pointerdown" event handler.
             * @param {PointerEvent} ev
             */
            const onPointerDown = (ev) => {
                preventClick = false;
                updatePointerPosition(ev);

                const target = /** @type {HTMLElement} */ (ev.target);
                const initiationDelay =
                    ev.pointerType === "touch" ? ctx.touchDelay : ctx.delay;

                // A drag sequence can still be in progress if the pointerup occurred
                // outside of the window.
                dragEnd(null);

                const fullSelectorEl = /** @type {HTMLElement} */ (
                    target.closest(ctx.fullSelector)
                );
                if (
                    ev.button !== LEFT_CLICK ||
                    !ctx.enable() ||
                    !fullSelectorEl ||
                    (ctx.ignoreSelector && target.closest(ctx.ignoreSelector)) ||
                    ctx.preventDrag(fullSelectorEl)
                ) {
                    return;
                }

                // Firefox: `overflow: hidden` elements block mouseenter/mouseleave on
                // elements underneath (e.g. dragging a card by its heading), so prevent
                // default on pointerdown to let pointer events fire properly.
                // https://bugzilla.mozilla.org/show_bug.cgi?id=1352061
                // https://bugzilla.mozilla.org/show_bug.cgi?id=339293
                safePrevent(ev);
                target.focus();
                let activeElement = document.activeElement;
                while (activeElement?.nodeName === "IFRAME") {
                    activeElement = /** @type {HTMLIFrameElement} */ (activeElement)
                        .contentDocument?.activeElement;
                }
                if (activeElement && !activeElement.contains(target)) {
                    /** @type {HTMLElement} */ (activeElement).blur();
                }

                const currentTarget = /** @type {HTMLElement} */ (ev.currentTarget);
                const { pointerId } = ev;
                ctx.current.initialPosition = { ...ctx.pointer };

                if (target.hasPointerCapture(pointerId)) {
                    target.releasePointerCapture(pointerId);
                }

                // From this point a drag sequence may start: attach the global
                // drag-following listeners (removed at drag end by the cleanup
                // manager).
                attachDragListeners();

                if (initiationDelay) {
                    if (hasTouch()) {
                        if (ev.pointerType === "touch") {
                            dom.addClass(
                                target.closest(ctx.elementSelector),
                                "o_touch_bounce",
                            );
                        }
                        if (isBrowserFirefox()) {
                            // On Firefox mobile, long-touch events trigger an unpreventable
                            // context menu to appear. To prevent this, all linkes are removed
                            // from the dragged elements during the drag sequence.
                            const links = [...currentTarget.querySelectorAll("[href]")];
                            if (currentTarget.hasAttribute("href")) {
                                links.unshift(currentTarget);
                            }
                            for (const link of links) {
                                dom.removeAttribute(link, "href");
                            }
                        }
                        if (isIOS()) {
                            // On Safari mobile, any image can be dragged regardless
                            // of the 'user-select' property.
                            for (const image of currentTarget.getElementsByTagName(
                                "img",
                            )) {
                                dom.setAttribute(image, "draggable", false);
                            }
                        }
                    }

                    ctx.current.timeout = browser.setTimeout(() => {
                        ctx.current.initialPosition = { ...ctx.pointer };

                        willStartDrag(target);

                        const { x: px, y: py } = ctx.pointer;
                        const { x, y, width, height } = dom.getRect(
                            ctx.current.element,
                        );
                        if (px < x || x + width < px || py < y || y + height < py) {
                            // Pointer left the target (the timeout is cleared in dragEnd)
                            dragEnd(null);
                        }
                    }, initiationDelay);
                    cleanup.add(() => browser.clearTimeout(ctx.current.timeout));
                } else {
                    willStartDrag(target);
                }
            };

            /**
             * Window "pointermove" event handler.
             * @param {PointerEvent} ev
             */
            const onPointerMove = (ev) => {
                updatePointerPosition(ev);

                if (!ctx.current.element || !ctx.enable()) {
                    return;
                }

                safePrevent(ev);

                if (!state.dragging) {
                    if (!canStartDrag()) {
                        return;
                    }
                    dragStart();
                } else if (
                    !params.allowDisconnected &&
                    !ctx.current.element.isConnected
                ) {
                    return dragEnd(null);
                }

                if (ctx.followCursor) {
                    updateElementPosition();
                }

                callBuildHandler("onDrag");
            };

            /**
             * Window "pointerup" event handler.
             * @param {PointerEvent} ev
             */
            const onPointerUp = (ev) => {
                updatePointerPosition(ev);
                dragEnd(/** @type {HTMLElement} */ (ev.target));
            };

            /**
             * Updates the position of the current dragged element according to
             * the current pointer position.
             */
            const updateElementPosition = () => {
                const { containerRect, element, elementRect, offset } = ctx.current;
                const { width: ew, height: eh } = elementRect;
                const { x: cx, y: cy, width: cw, height: ch } = containerRect;

                dom.addStyle(element, {
                    left: `${clamp(ctx.pointer.x - offset.x, cx, cx + cw - ew)}px`,
                    top: `${clamp(ctx.pointer.y - offset.y, cy, cy + ch - eh)}px`,
                });
            };

            /**
             * Updates the current pointer position from a given event.
             * @param {PointerEvent} ev
             */
            const updatePointerPosition = (ev) => {
                ctx.pointer.x = ev.clientX;
                ctx.pointer.y = ev.clientY;
            };

            const updateRects = () => {
                const { current } = ctx;
                const { container, element, scrollParentX, scrollParentY } = current;
                // Container rect
                current.containerRect = dom.getRect(container, {
                    adjust: true,
                });
                // If the scrolling element is within an iframe and the draggable
                // element is outside this iframe, the offsets must be computed taking
                // into account the iframe.
                let iframeOffsetX = 0;
                let iframeOffsetY = 0;
                const iframeEl = /** @type {HTMLIFrameElement} */ (
                    container.ownerDocument.defaultView.frameElement
                );
                if (iframeEl && !iframeEl.contentDocument?.contains(element)) {
                    const { x, y } = dom.getRect(/** @type {HTMLElement} */ (iframeEl));
                    iframeOffsetX = x;
                    iframeOffsetY = y;
                    current.containerRect.x += iframeOffsetX;
                    current.containerRect.y += iframeOffsetY;
                }
                // Adjust container rect according to its overflowing size
                current.containerRect.width = container.scrollWidth;
                current.containerRect.height = container.scrollHeight;
                // ScrollParent rect
                current.scrollParentXRect = null;
                current.scrollParentYRect = null;
                if (ctx.edgeScrolling.enabled) {
                    // Adjust container rect according to scrollParents
                    if (scrollParentX) {
                        current.scrollParentXRect = dom.getRect(scrollParentX, {
                            adjust: true,
                        });
                        current.scrollParentXRect.x += iframeOffsetX;
                        current.scrollParentXRect.y += iframeOffsetY;
                        const right = Math.min(
                            current.containerRect.left + container.scrollWidth,
                            current.scrollParentXRect.right,
                        );
                        current.containerRect.x = Math.max(
                            current.containerRect.x,
                            current.scrollParentXRect.x,
                        );
                        current.containerRect.width = right - current.containerRect.x;
                    }
                    if (scrollParentY) {
                        current.scrollParentYRect = dom.getRect(scrollParentY, {
                            adjust: true,
                        });
                        current.scrollParentYRect.x += iframeOffsetX;
                        current.scrollParentYRect.y += iframeOffsetY;
                        const bottom = Math.min(
                            current.containerRect.top + container.scrollHeight,
                            current.scrollParentYRect.bottom,
                        );
                        current.containerRect.y = Math.max(
                            current.containerRect.y,
                            current.scrollParentYRect.y,
                        );
                        current.containerRect.height = bottom - current.containerRect.y;
                    }
                }

                // Element rect
                ctx.current.elementRect = dom.getRect(element);
            };

            /**
             * @param {Element} target
             */
            const willStartDrag = (target) => {
                ctx.current.element = target.closest(ctx.elementSelector);
                ctx.current.container = ctx.ref.el;

                cleanup.add(() => (ctx.current = {}));
                state.willDrag = true;

                callBuildHandler("onWillStartDrag");

                if (hasTouch()) {
                    // Prevents panning/zooming after a long press
                    dom.addListener(window, "touchmove", safePrevent, {
                        passive: false,
                        noAddedStyle: true,
                    });
                    if (params.iframeWindow) {
                        dom.addListener(params.iframeWindow, "touchmove", safePrevent, {
                            passive: false,
                            noAddedStyle: true,
                        });
                    }
                }
            };

            // Initialize helpers
            const cleanup = makeCleanupManager(() => (state.dragging = false));
            const effectCleanup = makeCleanupManager();
            const dom = makeDOMHelpers(cleanup);

            const helpers = {
                ...dom,
                addCleanup: cleanup.add,
                addEffectCleanup: effectCleanup.add,
                callHandler,
            };

            // Component infos
            const state = setupHooks.wrapState({
                dragging: false,
                willDrag: false,
            });

            // Basic error handling asserting that the parameters are valid.
            for (const prop of Object.keys(allAcceptedParams)) {
                const type = typeof params[prop];
                const acceptedTypes = allAcceptedParams[prop].map((t) =>
                    t.name.toLowerCase(),
                );
                if (params[prop]) {
                    if (!acceptedTypes.includes(type)) {
                        throw makeError(
                            `invalid type for property "${prop}" in parameters: expected { ${acceptedTypes.join(
                                ", ",
                            )} } and got ${type}`,
                        );
                    }
                } else if (MANDATORY_PARAMS.includes(prop) && !defaultParams[prop]) {
                    throw makeError(
                        `missing required property "${prop}" in parameters`,
                    );
                }
            }

            /** @type {DraggableHookContext} */
            const ctx = {
                enable: () => false,
                preventDrag: () => false,
                ref: params.ref,
                ignoreSelector: null,
                fullSelector: null,
                followCursor: true,
                cursor: null,
                pointer: { x: 0, y: 0 },
                edgeScrolling: { enabled: true },
                get dragging() {
                    return state.dragging;
                },
                get willDrag() {
                    return state.willDrag;
                },
                // Current context
                current: {},
            };

            // Effect depending on the params to update them.
            setupHooks.setup(
                (...deps) => {
                    // Rebuild the computed params from the flat dep values
                    // (see `computeParams`): same `prop in params` presence
                    // check, same `paramKeys` order, and `enable` is wrapped
                    // with `toFunction` here so a raw (stable) value can be
                    // used as the dependency.
                    /** @type {Record<string, any>} */
                    const computedParams = { enable: () => true };
                    paramKeys.forEach((prop, index) => {
                        if (prop in params) {
                            computedParams[prop] =
                                prop === "enable"
                                    ? toFunction(deps[index])
                                    : deps[index];
                        }
                    });
                    /** @type {Record<string, any>} */
                    const actualParams = {
                        ...defaultParams,
                        ...omit(computedParams, "edgeScrolling"),
                    };
                    if (computedParams.edgeScrolling) {
                        actualParams.edgeScrolling = {
                            ...actualParams.edgeScrolling,
                            ...computedParams.edgeScrolling,
                        };
                    }

                    if (!ctx.ref.el) {
                        return;
                    }

                    // Enable getter
                    ctx.enable = actualParams.enable;

                    // Dragging constraint
                    if (actualParams.preventDrag) {
                        ctx.preventDrag = actualParams.preventDrag;
                    }

                    // Selectors
                    ctx.elementSelector = actualParams.elements;
                    if (!ctx.elementSelector) {
                        throw makeError(
                            `no value found by "elements" selector: ${ctx.elementSelector}`,
                        );
                    }
                    const allSelectors = [ctx.elementSelector];
                    ctx.cursor = actualParams.cursor || null;
                    if (actualParams.handle) {
                        allSelectors.push(actualParams.handle);
                    }
                    if (actualParams.ignore) {
                        ctx.ignoreSelector = actualParams.ignore;
                    }
                    ctx.fullSelector = allSelectors.join(" ");

                    // Edge scrolling
                    Object.assign(ctx.edgeScrolling, actualParams.edgeScrolling);

                    // Delay & tolerance
                    ctx.delay = actualParams.delay;
                    // Touch delay resolution (documented contract: `touchDelay`
                    // is "same as delay, but specific to touch environments"):
                    //  1. an EXPLICIT `touchDelay` param always wins on touch;
                    //  2. otherwise an explicit `delay` also applies to touch;
                    //  3. otherwise the built-in touch default (300ms).
                    // `computedParams` only holds caller-provided params, so it
                    // distinguishes explicit values from `defaultParams`
                    // fallbacks (the old `delay || touchDelay` let a mere
                    // `delay` override an explicit `touchDelay`).
                    ctx.touchDelay =
                        computedParams.touchDelay ??
                        computedParams.delay ??
                        actualParams.touchDelay;
                    ctx.tolerance = actualParams.tolerance;

                    callBuildHandler("onComputeParams", {
                        params: actualParams,
                    });

                    // Calls effect cleanup functions when preparing to re-render.
                    return effectCleanup.cleanup;
                },
                () => computeParams(params),
            );
            // Firefox currently (119.0.1) does not handle our pointer events
            // nicely when they happen from within the iframe. To work around
            // this, we use mouse events instead of pointer events.
            const useMouseEvents =
                isBrowserFirefox() && !hasTouch() && params.iframeWindow;
            // Effect depending on the `ref.el` to add triggering pointer events listener.
            setupHooks.setup(
                (el) => {
                    if (el) {
                        const { add, cleanup } = makeCleanupManager();
                        const { addListener } = makeDOMHelpers({
                            add,
                            cleanup,
                        });
                        const event = useMouseEvents ? "mousedown" : "pointerdown";
                        addListener(el, event, onPointerDown, {
                            noAddedStyle: true,
                        });
                        addListener(el, "click", onClick);
                        if (hasTouch()) {
                            addListener(el, "contextmenu", safePrevent);
                            // Non-passive touchstart listener: allows subsequent
                            // "touchmove" events to be cancelable, preventing parasitic
                            // "touchcancel" events. Don't prevent touchstart itself —
                            // it drives native swipe scrolling.
                            addListener(el, "touchstart", () => {}, {
                                passive: false,
                                noAddedStyle: true,
                            });
                        }
                        return cleanup;
                    }
                },
                () => [ctx.ref.el],
            );
            // Global drag-following event handlers. The (throttled) pointermove
            // handler is created once per hook instance, but the listeners are
            // only attached for the duration of a drag sequence
            // (@see attachDragListeners).
            const throttledOnPointerMove = setupHooks.throttle(onPointerMove);
            /**
             * Attaches the global drag-following listeners ("pointermove",
             * "pointerup", "pointercancel", capture "keydown") for the duration
             * of a single drag sequence, removed via a single AbortController at
             * drag end/cancel/unmount so idle hook instances do zero pointer work.
             */
            const attachDragListeners = () => {
                const controller = new AbortController();
                /**
                 * @param {string} type
                 * @param {any} listener
                 * @param {AddEventListenerOptions} [options]
                 */
                const addWindowListener = (type, listener, options = {}) => {
                    options.signal = controller.signal;
                    if (params.iframeWindow) {
                        params.iframeWindow.addEventListener(type, listener, options);
                    }
                    window.addEventListener(type, listener, options);
                };
                addWindowListener(
                    useMouseEvents ? "mousemove" : "pointermove",
                    throttledOnPointerMove,
                    { passive: false },
                );
                addWindowListener(
                    useMouseEvents ? "mouseup" : "pointerup",
                    onPointerUp,
                );
                addWindowListener("pointercancel", onPointerCancel);
                addWindowListener("keydown", onKeyDown, { capture: true });
                cleanup.add(() => controller.abort());
            };
            setupHooks.teardown(() => dragEnd(null));

            return state;
        },
    }[hookName];
}
