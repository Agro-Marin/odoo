/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { pick } from "@web/core/utils/collections/objects";
import { makeNativeDraggableHook } from "@web/core/utils/dnd";
import { closest, touching } from "@web/core/utils/dom/ui";
import { throttleForAnimation } from "@web/core/utils/timing";

/** @typedef {import("@web/core/utils/dnd/draggable_hook_builder").DraggableHandlerParams} DraggableHandlerParams */
/** @typedef {import("@web/core/utils/dnd/draggable_hook_builder").DraggableBuilderParams} DraggableBuilderParams */
/** @typedef {import("@web/core/utils/dnd/draggable").DraggableParams} DraggableParams */

/** @typedef {DraggableHandlerParams & { dropzone: HTMLElement | null, helper: HTMLElement }} DragAndDropHandlerParams */
/** @typedef {DraggableHandlerParams & { helper: HTMLElement }} DragAndDropStartParams */
/** @typedef {DraggableHandlerParams & { dropzone: HTMLElement }} DropzoneHandlerParams */
/**
 * @typedef DragAndDropParams
 * @extends {DraggableParams}
 * @property {(() => Array)} dropzones
 * @property {(() => HTMLElement)} helper
 * @property {(() => HTMLElement)} scrollingElement
 * @property {(params: DragAndDropStartParams) => any} [onDragStart]
 * @property {(params: DropzoneHandlerParams) => any} [dropzoneOver]
 * @property {(params: DropzoneHandlerParams) => any} [dropzoneOut]
 * @property {(params: DragAndDropHandlerParams) => any} [onDrag]
 * @property {(params: DragAndDropHandlerParams) => any} [onDragEnd]
 */
/**
 * @typedef NativeDraggableState
 * @property {(params: DraggableParams) => any} update
 * @property {import("@web/core/utils/dnd/draggable").DraggableState} state
 * @property {() => any} destroy
 */
/**
 * @param {DraggableBuilderParams} hookParams
 * @param {DraggableParams} initialParams
 * @returns {NativeDraggableState}
 */
export function useNativeDraggable(hookParams, initialParams) {
    const setupFunctions = new Map();
    const cleanupFunctions = [];
    const currentParams = { ...initialParams };
    const setupHooks = {
        wrapState: reactive,
        throttle: throttleForAnimation,
        addListener: (el, type, callback, options) => {
            el.addEventListener(type, callback, options);
            cleanupFunctions.push(() => el.removeEventListener(type, callback));
        },
        setup: (setupFn, depsFn) => setupFunctions.set(setupFn, depsFn),
        teardown: (cleanupFn) => {
            cleanupFunctions.push(cleanupFn);
        },
    };
    const el = initialParams.ref.el;
    el.classList.add("o_draggable");
    cleanupFunctions.push(() => el.classList.remove("o_draggable"));

    const draggableState = makeNativeDraggableHook({ setupHooks, ...hookParams })(
        currentParams,
    );
    draggableState.enable = true;
    const draggableComponent = {
        state: draggableState,
        update: (newParams) => {
            Object.assign(currentParams, newParams);
            setupFunctions.forEach((depsFn, setupFn) => setupFn(...depsFn()));
        },
        destroy: () => {
            cleanupFunctions.forEach((cleanupFn) => cleanupFn());
        },
    };
    draggableComponent.update({});
    return draggableComponent;
}

function updateElementPosition(el, { x, y }, styleFn, offset = { x: 0, y: 0 }) {
    return styleFn(el, { top: `${y - offset.y}px`, left: `${x - offset.x}px` });
}
const dragAndDropHookParams = {
    name: "useDragAndDrop",
    acceptedParams: {
        dropzones: [Function],
        scrollingElement: [Function],
        helper: [Function],
        extraWindow: [Object, Function],
    },
    edgeScrolling: { enabled: true },
    onComputeParams({ ctx, params }) {
        ctx.followCursor = false;
        ctx.getScrollingElement = params.scrollingElement;
        ctx.getHelper = params.helper;
        ctx.getDropZones = params.dropzones;
    },
    onWillStartDrag: ({ ctx }) => {
        ctx.current.container = ctx.getScrollingElement();
        ctx.current.helperOffset = { x: 0, y: 0 };
    },
    onDragStart: ({ ctx, addStyle, addCleanup }) => {
        ctx.current.helper = ctx.getHelper({ ...ctx.current, ...ctx.pointer });
        ctx.current.helper.style.position = "fixed";
        ctx.current.element.classList.remove("o_dragged");
        ctx.current.helper.style.cursor = ctx.cursor;
        ctx.current.helper.style.pointerEvents = "auto";

        const frameElement = ctx.current.helper.ownerDocument.defaultView.frameElement;
        if (frameElement) {
            addStyle(frameElement, { pointerEvents: "auto" });
        }

        addCleanup(() => ctx.current.helper.remove());

        updateElementPosition(
            ctx.current.helper,
            ctx.pointer,
            addStyle,
            ctx.current.helperOffset,
        );

        return pick(ctx.current, "element", "helper");
    },
    onDrag: ({ ctx, addStyle, callHandler }) => {
        ctx.current.helper.classList.add("o_draggable_dragging");

        updateElementPosition(
            ctx.current.helper,
            ctx.pointer,
            addStyle,
            ctx.current.helperOffset,
        );
        let helperRect = ctx.current.helper.getBoundingClientRect();
        helperRect = {
            x: helperRect.x,
            y: helperRect.y,
            width: helperRect.width,
            height: helperRect.height,
        };
        const dropzoneEl = closest(
            touching(ctx.getDropZones(), helperRect),
            helperRect,
        );
        if (
            ctx.current.dropzone?.el &&
            ctx.current.dropzone.el.classList.contains("oe_grid_zone")
        ) {
            ctx.current.dropzone.rect = ctx.current.dropzone.el.getBoundingClientRect();
        }
        if (
            ctx.current.dropzone &&
            (ctx.current.dropzone.el === dropzoneEl ||
                (!dropzoneEl &&
                    touching([ctx.current.helper], ctx.current.dropzone.rect).length >
                        0))
        ) {
            return pick(ctx.current, "element", "dropzone", "helper");
        }

        if (ctx.current.dropzone && dropzoneEl !== ctx.current.dropzone.el) {
            callHandler("dropzoneOut", {
                dropzone: ctx.current.dropzone,
                helper: ctx.current.helper,
            });
            delete ctx.current.dropzone;
        }

        if (dropzoneEl) {
            const rect = DOMRect.fromRect(dropzoneEl.getBoundingClientRect());
            ctx.current.dropzone = {
                el: dropzoneEl,
                rect: {
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                },
            };
            callHandler("dropzoneOver", {
                dropzone: ctx.current.dropzone,
                helper: ctx.current.helper,
            });
        }
        return pick(ctx.current, "element", "dropzone", "helper");
    },
    onDragEnd({ ctx }) {
        return pick(ctx.current, "element", "dropzone", "helper");
    },
};
/**
 * @param {DragAndDropParams} initialParams
 * @returns {NativeDraggableState}
 */
export function useDragAndDrop(initialParams) {
    return useNativeDraggable(dragAndDropHookParams, initialParams);
}
