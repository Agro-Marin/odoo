// @ts-check
/** @odoo-module native */

import { clamp } from "@web/core/utils/format/numbers";

/**
 * @import { DraggableHookContext } from "./draggable_hook_builder.js"
 */

/**
 * @param {DraggableHookContext} ctx
 * @param {PointerEvent} ev
 * @returns {void}
 */
export function updatePointerPosition(ctx, ev) {
    ctx.pointer.x = ev.clientX;
    ctx.pointer.y = ev.clientY;
}

/**
 * @param {DraggableHookContext} ctx
 * @returns {boolean}
 */
export function canStartDrag(ctx) {
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
 * @param {DraggableHookContext} ctx
 * @param {Record<string, any>} dom
 * @returns {void}
 */
export function updateElementPosition(ctx, dom) {
    const { containerRect, element, elementRect, offset } = ctx.current;
    const { width: ew, height: eh } = elementRect;
    const { x: cx, y: cy, width: cw, height: ch } = containerRect;

    dom.addStyle(element, {
        left: `${clamp(ctx.pointer.x - offset.x, cx, cx + cw - ew)}px`,
        top: `${clamp(ctx.pointer.y - offset.y, cy, cy + ch - eh)}px`,
    });
}

/**
 * @param {DraggableHookContext} ctx
 * @param {Record<string, any>} dom
 * @returns {void}
 */
export function updateRects(ctx, dom) {
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
            const xRect = dom.getRect(scrollParentX, { adjust: true });
            current.scrollParentXRect = xRect;
            xRect.x += iframeOffsetX;
            xRect.y += iframeOffsetY;
            const right = Math.min(
                current.containerRect.left + container.scrollWidth,
                xRect.right,
            );
            current.containerRect.x = Math.max(current.containerRect.x, xRect.x);
            current.containerRect.width = right - current.containerRect.x;
        }
        if (scrollParentY) {
            const yRect = dom.getRect(scrollParentY, { adjust: true });
            current.scrollParentYRect = yRect;
            yRect.x += iframeOffsetX;
            yRect.y += iframeOffsetY;
            const bottom = Math.min(
                current.containerRect.top + container.scrollHeight,
                yRect.bottom,
            );
            current.containerRect.y = Math.max(current.containerRect.y, yRect.y);
            current.containerRect.height = bottom - current.containerRect.y;
        }
    }

    ctx.current.elementRect = dom.getRect(element);
}

/**
 * @param {number} deltaTime
 * @param {DraggableHookContext} ctx
 * @param {{ updateRects: () => void, onDrag: () => void }} deps
 * @returns {void}
 */
export function handleEdgeScrolling(deltaTime, ctx, { updateRects, onDrag }) {
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
