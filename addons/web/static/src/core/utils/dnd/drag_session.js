// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { hasTouch, isBrowserFirefox, isIOS } from "@web/core/browser/feature_detection";
import { setRecurringAnimationFrame } from "@web/core/utils/timing";

import {
    canStartDrag,
    handleEdgeScrolling,
    updateElementPosition,
    updatePointerPosition,
    updateRects,
} from "./drag_geometry.js";
import {
    DRAGGED_CLASS,
    getScrollParents,
    LEFT_CLICK,
    makeCleanupManager,
    makeDOMHelpers,
    safePrevent,
    WHITE_LISTED_KEYS,
} from "./draggable_hook_builder_utils.js";

/**
 * @import { DraggableHookContext, DraggableHookCurrentContext } from "./draggable_hook_builder.js"
 */

/**
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

export class DragSession {
    /**
     * @param {{
     * ctx: DraggableHookContext,
     * state: { dragging: boolean, willDrag: boolean },
     * params: Record<string, any>,
     * hookParams: Record<string, any>,
     * }} deps
     */
    constructor({ ctx, state, params, hookParams }) {
        this.ctx = ctx;
        this.state = state;
        this.params = params;
        this.hookParams = hookParams;

        this.preventClick = false;

        this.cleanup = makeCleanupManager(() => {
            state.dragging = false;
            state.willDrag = false;
        });
        this.effectCleanup = makeCleanupManager();
        this.dom = makeDOMHelpers(this.cleanup);

        this.helpers = {
            ...this.dom,
            addCleanup: this.cleanup.add,
            addEffectCleanup: this.effectCleanup.add,
            callHandler: this.callHandler,
        };

        this.useMouseEvents = Boolean(
            isBrowserFirefox() && !hasTouch() && params.iframeWindow,
        );

        /** @type {(((ev: PointerEvent) => void) & { cancel: () => void }) | null} */
        this.throttledOnPointerMove = null;
    }

    /**
     * @param {string} hookHandlerName
     * @param {Record<any, any>} [arg]
     * @returns {void}
     */
    callBuildHandler = (hookHandlerName, arg = {}) => {
        if (typeof this.hookParams[hookHandlerName] !== "function") {
            return;
        }
        const returnValue = this.hookParams[hookHandlerName]({
            ctx: this.ctx,
            ...this.helpers,
            ...arg,
        });
        if (returnValue) {
            this.callHandler(hookHandlerName, returnValue);
        }
    };

    /**
     * @param {string} handlerName
     * @param {Record<any, any>} arg
     * @returns {void}
     */
    callHandler = (handlerName, arg) => {
        if (typeof this.params[handlerName] !== "function") {
            return;
        }
        try {
            this.params[handlerName]({ ...this.dom, ...this.ctx.pointer, ...arg });
        } catch (err) {
            this.dragEnd(null, true);
            throw err;
        }
    };

    /** @returns {void} */
    dragStart = () => {
        const { ctx, dom, params, state } = this;
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
                /** @type {HTMLElement} */ (ctx.current.container).ownerDocument,
                "scroll",
                markRectsDirty,
                { capture: true, passive: true },
            );
            const cleanupFn = setRecurringAnimationFrame((deltaTime) =>
                handleEdgeScrolling(deltaTime, ctx, {
                    updateRects: () => updateRects(ctx, dom),
                    onDrag: () => this.callBuildHandler("onDrag"),
                }),
            );
            this.cleanup.add(cleanupFn);
        }

        dom.addClass(ctx.current.element, DRAGGED_CLASS);

        this.callBuildHandler("onDragStart");
    };

    /**
     * @param {HTMLElement | null} target
     * @param {boolean} [inErrorState]
     * @returns {void}
     */
    dragEnd = (target, inErrorState) => {
        try {
            if (this.state.dragging) {
                this.preventClick = true;
                if (!inErrorState) {
                    if (
                        target &&
                        (this.params.allowDisconnected ||
                            this.ctx.current.element.isConnected)
                    ) {
                        this.callBuildHandler("onDrop", { target });
                    }
                    this.callBuildHandler("onDragEnd");
                }
            }
        } finally {
            this.cleanup.cleanup();
        }
    };

    /**
     * @param {PointerEvent} ev
     * @returns {void}
     */
    onClick = (ev) => {
        if (this.preventClick) {
            safePrevent(ev, { stop: true });
        }
    };

    /**
     * @param {KeyboardEvent} ev
     * @returns {void}
     */
    onKeyDown = (ev) => {
        if (!this.state.dragging || !this.ctx.enable()) {
            return;
        }
        if (!WHITE_LISTED_KEYS.includes(ev.key)) {
            safePrevent(ev, { stop: true });
            this.dragEnd(null);
        }
    };

    /** @returns {void} */
    onPointerCancel = () => {
        this.dragEnd(null);
    };

    /**
     * @param {PointerEvent} ev
     * @returns {void}
     */
    onPointerDown = (ev) => {
        const { ctx, dom } = this;
        this.preventClick = false;
        updatePointerPosition(ctx, ev);

        const target = /** @type {HTMLElement} */ (ev.target);
        const initiationDelay = ev.pointerType === "touch" ? ctx.touchDelay : ctx.delay;

        this.dragEnd(null);

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

        this.attachDragListeners();

        if (initiationDelay) {
            neutralizeTouchInterference(ev, target, currentTarget, {
                dom,
                elementSelector: /** @type {string} */ (ctx.elementSelector),
            });

            ctx.current.timeout = browser.setTimeout(() => {
                ctx.current.initialPosition = { ...ctx.pointer };
                this.willStartDrag(target);

                const { x: px, y: py } = ctx.pointer;
                const { x, y, width, height } = dom.getRect(ctx.current.element);
                if (px < x || x + width < px || py < y || y + height < py) {
                    this.dragEnd(null);
                }
            }, initiationDelay);
            this.cleanup.add(() => browser.clearTimeout(ctx.current.timeout));
        } else {
            this.willStartDrag(target);
        }
    };

    /**
     * @param {PointerEvent} ev
     * @returns {void}
     */
    onPointerMove = (ev) => {
        const { ctx, dom, params, state } = this;
        updatePointerPosition(ctx, ev);

        if (!ctx.current.element || !ctx.enable()) {
            return;
        }

        safePrevent(ev);

        if (!state.dragging) {
            if (!canStartDrag(ctx)) {
                return;
            }
            this.dragStart();
        } else if (!params.allowDisconnected && !ctx.current.element.isConnected) {
            return this.dragEnd(null);
        }

        if (ctx.followCursor) {
            updateElementPosition(ctx, dom);
        }

        this.callBuildHandler("onDrag");
    };

    /**
     * @param {PointerEvent} ev
     * @returns {void}
     */
    onPointerUp = (ev) => {
        updatePointerPosition(this.ctx, ev);
        this.dragEnd(/** @type {HTMLElement} */ (ev.target));
    };

    /**
     * @param {Element} target
     * @returns {void}
     */
    willStartDrag = (target) => {
        const { ctx, dom, params, state } = this;
        const element = /** @type {HTMLElement | null} */ (
            target.closest(/** @type {string} */ (ctx.elementSelector))
        );
        if (!element || !ctx.ref.el) {
            return;
        }
        ctx.current.element = element;
        ctx.current.container = ctx.ref.el;

        this.cleanup.add(
            () => (ctx.current = /** @type {DraggableHookCurrentContext} */ ({})),
        );
        state.willDrag = true;

        this.callBuildHandler("onWillStartDrag");

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

    /** @returns {void} */
    attachDragListeners = () => {
        const controller = new AbortController();
        /**
         * @param {string} type
         * @param {any} listener
         * @param {AddEventListenerOptions} [options]
         */
        const addWindowListener = (type, listener, options = {}) => {
            options.signal = controller.signal;
            if (this.params.iframeWindow) {
                this.params.iframeWindow.addEventListener(type, listener, options);
            }
            browser.addEventListener(type, listener, options);
        };
        addWindowListener(
            this.useMouseEvents ? "mousemove" : "pointermove",
            this.throttledOnPointerMove,
            { passive: false },
        );
        addWindowListener(
            this.useMouseEvents ? "mouseup" : "pointerup",
            this.onPointerUp,
        );
        addWindowListener("pointercancel", this.onPointerCancel);
        addWindowListener("keydown", this.onKeyDown, { capture: true });
        this.cleanup.add(() => controller.abort());
        this.cleanup.add(() => this.throttledOnPointerMove?.cancel());
    };

    /**
     * @param {HTMLElement} el
     * @returns {() => void}
     */
    attachElementListeners = (el) => {
        const { add, cleanup } = makeCleanupManager();
        const { addListener } = makeDOMHelpers({ add, cleanup });
        addListener(
            el,
            this.useMouseEvents ? "mousedown" : "pointerdown",
            this.onPointerDown,
            {
                noAddedStyle: true,
            },
        );
        addListener(el, "click", this.onClick);
        if (hasTouch()) {
            addListener(el, "contextmenu", safePrevent);
            addListener(el, "touchstart", () => {}, {
                passive: false,
                noAddedStyle: true,
            });
        }
        return cleanup;
    };
}
