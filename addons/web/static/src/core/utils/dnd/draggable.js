// @ts-check
/** @odoo-module native */

import { pick } from "@web/core/utils/collections/objects";
import { makeDraggableHook } from "@web/core/utils/dnd/draggable_hook_builder_owl";

/** @import { DraggableHandlerParams } from "@web/core/utils/dnd/draggable_hook_builder" */

/**
 * @typedef DraggableParams
 * @property {{ el: HTMLElement | null }} ref
 * @property {string} elements
 * @property {boolean | (() => boolean)} [enable]
 * @property {string | (() => string)} [handle]
 * @property {string | (() => string)} [ignore]
 * @property {string | (() => string)} [cursor]
 * @property {(params: DraggableHandlerParams) => any} [onDragStart]
 * @property {(params: DraggableHandlerParams) => any} [onDrag]
 * @property {(params: DraggableHandlerParams) => any} [onDragEnd]
 * @property {(params: DraggableHandlerParams) => any} [onDrop]
 */

/**
 * @typedef DraggableState
 * @property {boolean} dragging
 */

/** @type {(params: DraggableParams) => DraggableState} */
export const useDraggable = /** @type {any} */ (
    makeDraggableHook(
        /** @type {any} */ ({
            name: "useDraggable",
            onWillStartDrag: (/** @type {{ ctx: { current: any } }} */ { ctx }) =>
                pick(ctx.current, "element"),
            onDragStart: (/** @type {{ ctx: { current: any } }} */ { ctx }) =>
                pick(ctx.current, "element"),
            onDrag: (/** @type {{ ctx: { current: any } }} */ { ctx }) =>
                pick(ctx.current, "element"),
            onDragEnd: (/** @type {{ ctx: { current: any } }} */ { ctx }) =>
                pick(ctx.current, "element"),
            onDrop: (/** @type {{ ctx: { current: any } }} */ { ctx }) =>
                pick(ctx.current, "element"),
        }),
    )
);
