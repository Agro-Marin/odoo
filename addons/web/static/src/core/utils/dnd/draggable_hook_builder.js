// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dnd/draggable_hook_builder */

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
 * @typedef {ReturnType<typeof makeDOMHelpers>} DOMHelpers
 * @typedef DraggableBuilderParams
 * @property {string} [name="useAnonymousDraggable"]
 * @property {EdgeScrollingOptions} [edgeScrolling]
 * @property {Record<string, string[]>} [acceptedParams]
 * @property {Record<string, any>} [defaultParams]
 * @property {{
 *  addListener?: typeof import("@odoo/owl")["useExternalListener"];
 *  setup: typeof import("@odoo/owl")["useEffect"];
 *  teardown: typeof import("@odoo/owl")["onWillUnmount"];
 *  throttle: typeof import("@web/core/utils/timing")["useThrottleForAnimation"];
 *  wrapState: typeof import("@odoo/owl")["reactive"];
 * }} setupHooks
 * @property {(params: DraggableBuildHandlerParams) => any} onComputeParams
 * @property {(params: DraggableBuildHandlerParams) => any} onDragStart
 * @property {(params: DraggableBuildHandlerParams) => any} onDrag
 * @property {(params: DraggableBuildHandlerParams) => any} onDragEnd
 * @property {(params: DraggableBuildHandlerParams) => any} onDrop
 * @property {(params: DraggableBuildHandlerParams) => any} onWillStartDrag
 * @typedef {{
 *  ref: { el: HTMLElement | null };
 *  elementSelector?: string | null;
 *  ignoreSelector: string | null;
 *  fullSelector: string | null;
 *  followCursor: boolean;
 *  cursor: string | null;
 *  enable: () => boolean;
 *  preventDrag: (el: HTMLElement) => boolean;
 *  pointer: Position;
 *  edgeScrolling: EdgeScrollingOptions;
 *  delay?: number;
 *  tolerance?: number;
 *  touchDelay?: number;
 *  dragging: boolean;
 *  willDrag: boolean;
 *  current: DraggableHookCurrentContext;
 *  [key: string]: any;
 * }} DraggableHookContext
 * @typedef {{
 *  container: HTMLElement;
 *  containerRect: DOMRect;
 *  element: HTMLElement;
 *  elementRect: DOMRect;
 *  scrollParentX?: HTMLElement | null;
 *  scrollParentXRect?: DOMRect | null;
 *  scrollParentY?: HTMLElement | null;
 *  scrollParentYRect?: DOMRect | null;
 *  timeout?: ReturnType<typeof browser.setTimeout>;
 *  initialPosition: Position;
 *  offset: Position;
 *  [key: string]: any;
 * }} DraggableHookCurrentContext
 * @typedef EdgeScrollingOptions
 * @property {boolean} [enabled=true]
 * @property {number} speed
 * @property {number} threshold
 * @property {"horizontal"|"vertical"} [direction]
 * @typedef Position
 * @property {number} x
 * @property {number} y
 * @typedef {DOMHelpers & {
 *  ctx: DraggableHookContext,
 *  addCleanup(cleanupFn: () => any): void,
 *  addEffectCleanup(cleanupFn: () => any): void,
 *  callHandler(handlerName: string, arg: Record<any, any>): void,
 * }} DraggableBuildHandlerParams
 * @typedef {DOMHelpers & Position & { element: HTMLElement }} DraggableHandlerParams
 */

/**
 * Records where the pointer is, in the coordinate space the rest of the hook
 * compares against.
 *
 * @param {DraggableHookContext} ctx
 * @param {PointerEvent} ev
 * @returns {void}
 */
function updatePointerPosition(ctx, ev) {
    ctx.pointer.x = ev.clientX;
    ctx.pointer.y = ev.clientY;
}

/**
 * Whether the pointer has travelled far enough from the press to mean a drag
 * rather than a click.
 *
 * @param {DraggableHookContext} ctx
 * @returns {boolean}
 */
function canStartDrag(ctx) {
    const {
        pointer,
        current: { initialPosition },
    } = ctx;
    return (
        !ctx.tolerance ||
        Math.hypot(pointer.x - initialPosition.x, pointer.y - initialPosition.y) >=
            ctx.tolerance
    );
}

/**
 * Moves the dragged element under the cursor.
 *
 * @param {DraggableHookContext} ctx
 * @param {Record<string, any>} dom
 * @returns {void}
 */
function updateElementPosition(ctx, dom) {
    const { containerRect, element, elementRect, offset } = ctx.current;
    const { width: ew, height: eh } = elementRect;
    const { x: cx, y: cy, width: cw, height: ch } = containerRect;

    dom.addStyle(element, {
        left: `${clamp(ctx.pointer.x - offset.x, cx, cx + cw - ew)}px`,
        top: `${clamp(ctx.pointer.y - offset.y, cy, cy + ch - eh)}px`,
    });
}

/**
 * Recomputes the container and scroll-parent geometry the drag compares the
 * pointer against. Called once on drag start and again whenever a scroll or a
 * resize invalidates it.
 *
 * @param {DraggableHookContext} ctx
 * @param {Record<string, any>} dom
 * @returns {void}
 */
function updateRects(ctx, dom) {
    const { current } = ctx;
    const { container, element, scrollParentX, scrollParentY } = current;
    current.containerRect = dom.getRect(container, {
        adjust: true,
    });
    let iframeOffsetX = 0;
    let iframeOffsetY = 0;
    const iframeEl = /** @type {HTMLIFrameElement | null} */ (
        container.ownerDocument.defaultView?.frameElement ?? null
    );
    if (iframeEl && !iframeEl.contentDocument?.contains(element)) {
        const { x, y } = dom.getRect(/** @type {HTMLElement} */ (iframeEl));
        iframeOffsetX = x;
        iframeOffsetY = y;
        current.containerRect.x += iframeOffsetX;
        current.containerRect.y += iframeOffsetY;
    }
    current.containerRect.width = container.scrollWidth;
    current.containerRect.height = container.scrollHeight;
    current.scrollParentXRect = null;
    current.scrollParentYRect = null;
    if (ctx.edgeScrolling.enabled) {
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

    ctx.current.elementRect = dom.getRect(element);
}

/**
 * One frame of edge scrolling: if the pointer is within `threshold` of a scroll
 * parent's edge, scroll that parent proportionally to how close it is, and tell
 * the drag its geometry moved.
 *
 * Lifted out of the hook because it needs nothing from it but the context and
 * two callbacks — the enclosing method is 670 lines and every closure inside it
 * looked equally entangled until each one was measured.
 *
 * @param {number} deltaTime
 * @param {DraggableHookContext} ctx
 * @param {{ updateRects: () => void, onDrag: () => void }} deps
 * @returns {void}
 */
function handleEdgeScrolling(deltaTime, ctx, { updateRects, onDrag }) {
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
        let yRectY = yRect.y;
        const scrollParentYEl = /** @type {HTMLElement} */ (ctx.current.scrollParentY);
        if (scrollParentYEl === ctx.current.container.ownerDocument.scrollingElement) {
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
        const diffToScroll = (/** @type {[number, number]} */ [delta, sign]) =>
            (1 - Math.max(delta, 0) / threshold) * correctedSpeed * sign;
        if ((!direction || direction === "vertical") && diff.y) {
            const scrollParentY = /** @type {HTMLElement} */ (
                ctx.current.scrollParentY
            );
            const previousScrollTop = scrollParentY.scrollTop;
            scrollParentY.scrollBy({
                top: diffToScroll(diff.y),
                behavior: "instant",
            });
            scrolled ||= scrollParentY.scrollTop !== previousScrollTop;
        }
        if ((!direction || direction === "horizontal") && diff.x) {
            const scrollParentX = /** @type {HTMLElement} */ (
                ctx.current.scrollParentX
            );
            const previousScrollLeft = scrollParentX.scrollLeft;
            scrollParentX.scrollBy({
                left: diffToScroll(diff.x),
                behavior: "instant",
            });
            scrolled ||= scrollParentX.scrollLeft !== previousScrollLeft;
        }
        if (scrolled) {
            ctx.current.rectsDirty = true;
        }
    }
    if (scrolled || wereRectsDirty) {
        onDrag();
    }
}

/**
 * While a delayed press waits to become a drag, stop the mobile browser doing
 * its own thing with it: mark the element so the user sees the press landed,
 * drop hrefs on Firefox so releasing on a link does not navigate, and
 * un-draggable images on iOS so the OS drag does not take the pointer away.
 *
 * At module scope rather than inside the hook because it needs nothing from the
 * drag context beyond the selector — everything else is the event and the DOM
 * helpers, and those are passed. All three changes go through `dom`, so the
 * cleanup manager restores them when the press ends.
 *
 * @param {PointerEvent} ev
 * @param {HTMLElement} target
 * @param {HTMLElement} currentTarget
 * @param {{ dom: Record<string, any>, elementSelector: string }} deps
 * @returns {void}
 */
function neutralizeTouchInterference(
    ev,
    target,
    currentTarget,
    { dom, elementSelector },
) {
    if (!hasTouch()) {
        return;
    }
    if (ev.pointerType === "touch") {
        dom.addClass(target.closest(elementSelector), "o_touch_bounce");
    }
    if (isBrowserFirefox()) {
        const links = [...currentTarget.querySelectorAll("[href]")];
        if (currentTarget.hasAttribute("href")) {
            links.unshift(currentTarget);
        }
        for (const link of links) {
            dom.removeAttribute(link, "href");
        }
    }
    if (isIOS()) {
        for (const image of currentTarget.getElementsByTagName("img")) {
            dom.setAttribute(image, "draggable", false);
        }
    }
}

/**
 * @param {DraggableBuilderParams} hookParams
 * @returns {(params: Record<keyof typeof DEFAULT_ACCEPTED_PARAMS, any>) => { dragging: boolean }}
 */
export function makeNativeDraggableHook(hookParams) {
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

    const paramKeys = Object.keys(allAcceptedParams);

    /**
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
     * @param {string} reason
     * @returns {Error}
     */
    const makeError = (reason) => new Error(`Error in hook ${hookName}: ${reason}.`);

    return {
        [hookName](/** @type {Record<string, any>} */ params) {
            let preventClick = false;
            /**
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

            const dragStart = () => {
                state.dragging = true;
                state.willDrag = false;

                const isDocumentScrollingElement =
                    ctx.current.container ===
                    ctx.current.container.ownerDocument.scrollingElement;
                [ctx.current.scrollParentX, ctx.current.scrollParentY] =
                    isDocumentScrollingElement
                        ? [ctx.current.container, ctx.current.container]
                        : getScrollParents(ctx.current.container);

                updateRects(ctx, dom);
                const { x, y, width, height } = ctx.current.elementRect;

                ctx.current.offset = {
                    x: ctx.current.initialPosition.x - x,
                    y: ctx.current.initialPosition.y - y,
                };

                if (ctx.followCursor) {
                    dom.addStyle(ctx.current.element, {
                        width: `${width}px`,
                        height: `${height}px`,
                        "max-width": `${width}px`,
                        "max-height": `${height}px`,
                        position: "fixed !important",
                    });

                    updateElementPosition(ctx, dom);
                }

                dom.addClass(document.body, "pe-none", "user-select-none");
                if (params.iframeWindow) {
                    for (const iframe of document.getElementsByTagName("iframe")) {
                        if (iframe.contentWindow === params.iframeWindow) {
                            dom.addClass(iframe, "pe-none", "user-select-none");
                        }
                    }
                }
                if (ctx.cursor) {
                    dom.addStyle(document.body, { cursor: ctx.cursor });
                }

                if (
                    (ctx.current.scrollParentX || ctx.current.scrollParentY) &&
                    ctx.edgeScrolling.enabled
                ) {
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
                    const cleanupFn = setRecurringAnimationFrame((deltaTime) =>
                        handleEdgeScrolling(deltaTime, ctx, {
                            updateRects: () => updateRects(ctx, dom),
                            onDrag: () => callBuildHandler("onDrag"),
                        }),
                    );
                    cleanup.add(cleanupFn);
                }

                dom.addClass(ctx.current.element, DRAGGED_CLASS);

                callBuildHandler("onDragStart");
            };

            /**
             * @param {HTMLElement | null} target
             * @param {boolean} [inErrorState]
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
                    cleanup.cleanup();
                }
            };

            /**
             * @param {PointerEvent} ev
             */
            const onClick = (ev) => {
                if (preventClick) {
                    safePrevent(ev, { stop: true });
                }
            };

            /**
             * @param {KeyboardEvent} ev
             */
            const onKeyDown = (ev) => {
                if (!state.dragging || !ctx.enable()) {
                    return;
                }
                if (!WHITE_LISTED_KEYS.includes(ev.key)) {
                    safePrevent(ev, { stop: true });

                    dragEnd(null);
                }
            };

            const onPointerCancel = () => {
                dragEnd(null);
            };

            /**
             * @param {PointerEvent} ev
             */
            const onPointerDown = (ev) => {
                preventClick = false;
                updatePointerPosition(ctx, ev);

                const target = /** @type {HTMLElement} */ (ev.target);
                const initiationDelay =
                    ev.pointerType === "touch" ? ctx.touchDelay : ctx.delay;

                dragEnd(null);

                const fullSelectorEl = /** @type {HTMLElement | null} */ (
                    target.closest(/** @type {string} */ (ctx.fullSelector))
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

                safePrevent(ev);
                target.focus();
                let activeElement = document.activeElement;
                while (activeElement?.nodeName === "IFRAME") {
                    activeElement =
                        /** @type {HTMLIFrameElement} */ (activeElement).contentDocument
                            ?.activeElement ?? null;
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

                attachDragListeners();

                if (initiationDelay) {
                    neutralizeTouchInterference(ev, target, currentTarget, {
                        dom,
                        elementSelector: /** @type {string} */ (ctx.elementSelector),
                    });

                    ctx.current.timeout = browser.setTimeout(() => {
                        ctx.current.initialPosition = { ...ctx.pointer };

                        willStartDrag(target);

                        const { x: px, y: py } = ctx.pointer;
                        const { x, y, width, height } = dom.getRect(
                            ctx.current.element,
                        );
                        if (px < x || x + width < px || py < y || y + height < py) {
                            dragEnd(null);
                        }
                    }, initiationDelay);
                    cleanup.add(() => browser.clearTimeout(ctx.current.timeout));
                } else {
                    willStartDrag(target);
                }
            };

            /**
             * @param {PointerEvent} ev
             */
            const onPointerMove = (ev) => {
                updatePointerPosition(ctx, ev);

                if (!ctx.current.element || !ctx.enable()) {
                    return;
                }

                safePrevent(ev);

                if (!state.dragging) {
                    if (!canStartDrag(ctx)) {
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
                    updateElementPosition(ctx, dom);
                }

                callBuildHandler("onDrag");
            };

            /**
             * @param {PointerEvent} ev
             */
            const onPointerUp = (ev) => {
                updatePointerPosition(ctx, ev);
                dragEnd(/** @type {HTMLElement} */ (ev.target));
            };

            /**
             * @param {PointerEvent} ev
             */
            /**
             * @param {Element} target
             */
            const willStartDrag = (target) => {
                const element = /** @type {HTMLElement | null} */ (
                    target.closest(/** @type {string} */ (ctx.elementSelector))
                );
                if (!element || !ctx.ref.el) {
                    return;
                }
                ctx.current.element = element;
                ctx.current.container = ctx.ref.el;

                cleanup.add(
                    () =>
                        (ctx.current = /** @type {DraggableHookCurrentContext} */ ({})),
                );
                state.willDrag = true;

                callBuildHandler("onWillStartDrag");

                if (hasTouch()) {
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

            const cleanup = makeCleanupManager(() => {
                state.dragging = false;
                state.willDrag = false;
            });
            const effectCleanup = makeCleanupManager();
            const dom = makeDOMHelpers(cleanup);

            const helpers = {
                ...dom,
                addCleanup: cleanup.add,
                addEffectCleanup: effectCleanup.add,
                callHandler,
            };

            const state = setupHooks.wrapState({
                dragging: false,
                willDrag: false,
            });

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
                edgeScrolling: {
                    ...DEFAULT_DEFAULT_PARAMS.edgeScrolling,
                    enabled: true,
                },
                get dragging() {
                    return state.dragging;
                },
                get willDrag() {
                    return state.willDrag;
                },
                // Empty until `willStartDrag` fills it, and emptied again by
                // the cleanup it registers. Everything that reads it runs
                // between those two points, which is the state the type
                // describes.
                current: /** @type {DraggableHookCurrentContext} */ ({}),
            };

            setupHooks.setup(
                (...deps) => {
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

                    ctx.enable = actualParams.enable;

                    if (actualParams.preventDrag) {
                        ctx.preventDrag = actualParams.preventDrag;
                    }

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

                    Object.assign(ctx.edgeScrolling, actualParams.edgeScrolling);

                    ctx.delay = actualParams.delay;
                    ctx.touchDelay =
                        computedParams.touchDelay ??
                        computedParams.delay ??
                        actualParams.touchDelay;
                    ctx.tolerance = actualParams.tolerance;

                    callBuildHandler("onComputeParams", {
                        params: actualParams,
                    });

                    return effectCleanup.cleanup;
                },
                () => computeParams(params),
            );
            const useMouseEvents =
                isBrowserFirefox() && !hasTouch() && params.iframeWindow;
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
            const throttledOnPointerMove = setupHooks.throttle(onPointerMove);
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
                    browser.addEventListener(type, listener, options);
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
