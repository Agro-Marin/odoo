// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dnd/sortable */

import { pick } from "@web/core/utils/collections/objects";
import {
    DRAGGED_CLASS,
    makeNativeDraggableHook,
} from "@web/core/utils/dnd/draggable_hook_builder";

/** @import { DraggableHandlerParams } from "@web/core/utils/dnd/draggable_hook_builder" */
/** @typedef {DraggableHandlerParams & { group: HTMLElement | null }} SortableHandlerParams */

/**
 * @typedef SortableParams
 * @property {{ el: HTMLElement | null }} ref
 * @property {string} elements
 * @property {boolean | (() => boolean)} [enable]
 * @property {number} [delay]
 * @property {number} [touchDelay]
 * @property {string | false | (() => string | false)} [groups]
 * @property {string | (() => string)} [handle]
 * @property {string | (() => string)} [ignore]
 * @property {boolean | (() => boolean)} [connectGroups]
 * @property {string | (() => string)} [cursor]
 * @property {boolean} [clone]
 * @property {string[]} [placeholderClasses]
 * @property {boolean} [applyChangeOnDrop]
 * @property {string[]} [followingElementClasses]
 * @property {(params: SortableHandlerParams) => any} [onDragStart]
 * @property {(params: DraggableHandlerParams) => any} [onElementEnter]
 * @property {(params: DraggableHandlerParams) => any} [onElementLeave]
 * @property {(params: SortableHandlerParams) => any} [onGroupEnter]
 * @property {(params: SortableHandlerParams) => any} [onGroupLeave]
 * @property {(params: SortableHandlerParams) => any} [onDragEnd]
 * @property {(params: DropParams) => any} [onDrop]
 */

/**
 * @typedef DropParams
 * @property {HTMLElement} element
 * @property {HTMLElement | null} group
 * @property {HTMLElement | null} previous
 * @property {HTMLElement | null} next
 * @property {HTMLElement | null} parent
 */

/**
 * @typedef SortableState
 * @property {boolean} dragging
 */

/** @type {any} */
const hookParams = {
    name: "useSortable",
    acceptedParams: {
        groups: [String, Function],
        connectGroups: [Boolean, Function],
        clone: [Boolean],
        placeholderClasses: [Object],
        applyChangeOnDrop: [Boolean],
        followingElementClasses: [Object],
    },
    defaultParams: {
        connectGroups: false,
        edgeScrolling: { speed: 20, threshold: 60 },
        groupSelector: null,
        clone: true,
        placeholderClasses: [],
        applyChangeOnDrop: false,
        followingElementClasses: [],
    },

    onComputeParams(
        /** @type {{ ctx: Record<string, any>, params: Record<string, any> }} */ {
            ctx,
            params,
        },
    ) {
        ctx.groupSelector = params.groups || null;
        if (ctx.groupSelector) {
            ctx.fullSelector = [ctx.groupSelector, ctx.fullSelector].join(" ");
        }

        ctx.connectGroups = params.connectGroups;

        ctx.placeholderClone = params.clone;
        ctx.placeholderClasses = params.placeholderClasses;
        ctx.applyChangeOnDrop = params.applyChangeOnDrop;
        ctx.followingElementClasses = params.followingElementClasses;
    },

    onDragStart(
        /**
         * @type {{ ctx: Record<string, any>, addListener: Function, addStyle: Function, callHandler: Function }}
         */ { ctx, addListener, addStyle, callHandler },
    ) {
        const { connectGroups, current, elementSelector, groupSelector, ref } = ctx;

        /**
         * @param {HTMLElement} element
         */
        const onElementPointerEnter = (element) => {
            if (
                connectGroups ||
                !groupSelector ||
                current.group === element.closest(groupSelector)
            ) {
                const pos = current.placeHolder.compareDocumentPosition(element);
                if (pos === Node.DOCUMENT_POSITION_PRECEDING) {
                    element.before(current.placeHolder);
                } else if (pos === Node.DOCUMENT_POSITION_FOLLOWING) {
                    element.after(current.placeHolder);
                }
            }
            callHandler("onElementEnter", { element });
        };

        /**
         * @param {HTMLElement} element
         */
        const onElementPointerLeave = (element) => {
            callHandler("onElementLeave", { element });
        };

        /**
         * @param {HTMLElement} element
         */
        const onElementComplexPointerEnter = (element) => {
            if (ctx.haveAlreadyChanged) {
                return;
            }
            const siblingArray = [
                .../** @type {HTMLElement} */ (element.parentElement).children,
            ].filter(
                (el) =>
                    el === current.placeHolder ||
                    (el.matches(elementSelector) &&
                        !el.classList.contains(DRAGGED_CLASS)),
            );
            const elementIndex = siblingArray.indexOf(element);
            const placeholderIndex = siblingArray.indexOf(current.placeHolder);
            const isDirectSibling = Math.abs(elementIndex - placeholderIndex) === 1;
            if (
                connectGroups ||
                !groupSelector ||
                current.group === element.closest(groupSelector)
            ) {
                const pos = current.placeHolder.compareDocumentPosition(element);
                if (isDirectSibling) {
                    if (pos === Node.DOCUMENT_POSITION_PRECEDING) {
                        element.before(current.placeHolder);
                        ctx.haveAlreadyChanged = true;
                    } else if (pos === Node.DOCUMENT_POSITION_FOLLOWING) {
                        element.after(current.placeHolder);
                        ctx.haveAlreadyChanged = true;
                    }
                } else {
                    if (pos === Node.DOCUMENT_POSITION_FOLLOWING) {
                        element.before(current.placeHolder);
                        ctx.haveAlreadyChanged = true;
                    } else if (pos === Node.DOCUMENT_POSITION_PRECEDING) {
                        element.after(current.placeHolder);
                        ctx.haveAlreadyChanged = true;
                    }
                }
            }
            callHandler("onElementEnter", { element });
        };

        /**
         * @param {HTMLElement} element
         * @param {EventTarget | null} relatedTarget
         */
        const onElementComplexPointerLeave = (element, relatedTarget) => {
            if (ctx.haveAlreadyChanged) {
                return;
            }
            const relatedElement = /** @type {HTMLElement} */ (relatedTarget);
            if (!relatedElement) {
                return;
            }
            const elementRect = element.getBoundingClientRect();
            const relatedElementRect = relatedElement.getBoundingClientRect();

            const siblingArray = [
                .../** @type {HTMLElement} */ (element.parentElement).children,
            ].filter(
                (el) =>
                    el === current.placeHolder ||
                    (el.matches(elementSelector) &&
                        !el.classList.contains(DRAGGED_CLASS)),
            );
            const pointerOnSiblings = siblingArray.includes(relatedElement);
            const elementIndex = siblingArray.indexOf(element);
            const isFirst = elementIndex === 0;
            const isAbove = relatedElementRect.top <= elementRect.top;
            const isLast = elementIndex === siblingArray.length - 1;
            const isBelow = relatedElementRect.bottom >= elementRect.bottom;
            const pos = current.placeHolder.compareDocumentPosition(element);
            if (!pointerOnSiblings) {
                if (isFirst && isAbove && pos === Node.DOCUMENT_POSITION_PRECEDING) {
                    element.before(current.placeHolder);
                    ctx.haveAlreadyChanged = true;
                } else if (
                    isLast &&
                    isBelow &&
                    pos === Node.DOCUMENT_POSITION_FOLLOWING
                ) {
                    element.after(current.placeHolder);
                    ctx.haveAlreadyChanged = true;
                }
            }
            callHandler("onElementLeave", { element });
        };

        /**
         * @param {HTMLElement} group
         */
        const onGroupPointerEnter = (group) => {
            group.appendChild(current.placeHolder);
            callHandler("onGroupEnter", { group });
        };

        /**
         * @param {HTMLElement} group
         */
        const onGroupPointerLeave = (group) => {
            callHandler("onGroupLeave", { group });
        };

        if (ctx.placeholderClone) {
            const { width, height } = current.elementRect;

            addStyle(current.placeHolder, {
                visibility: "hidden",
                display: "block",
                width: `${width}px`,
                height: `${height}px`,
            });
        }

        const onElementEnter = ctx.placeholderClone
            ? onElementPointerEnter
            : onElementComplexPointerEnter;
        const onElementLeave = ctx.placeholderClone
            ? onElementPointerLeave
            : onElementComplexPointerLeave;

        /**
         * @param {EventTarget | null} node
         * @returns {HTMLElement | null}
         */
        const closestElementOf = (node) => {
            if (!(node instanceof Element)) {
                return null;
            }
            const element = /** @type {HTMLElement | null} */ (
                node.closest(elementSelector)
            );
            return element &&
                element !== current.element &&
                element !== current.placeHolder &&
                ref.el.contains(element)
                ? element
                : null;
        };

        /**
         * @param {EventTarget | null} node
         * @returns {HTMLElement | null}
         */
        const closestGroupOf = (node) => {
            if (!(node instanceof Element)) {
                return null;
            }
            const group = /** @type {HTMLElement | null} */ (
                node.closest(groupSelector)
            );
            return group && ref.el.contains(group) ? group : null;
        };

        const trackGroups = Boolean(connectGroups && groupSelector);

        /**
         * @param {PointerEvent} ev
         */
        const onPointerOver = (ev) => {
            if (trackGroups) {
                const group = closestGroupOf(ev.target);
                if (group && group !== closestGroupOf(ev.relatedTarget)) {
                    onGroupPointerEnter(group);
                }
            }
            const element = closestElementOf(ev.target);
            if (element && element !== closestElementOf(ev.relatedTarget)) {
                onElementEnter(element);
            }
        };

        /**
         * @param {PointerEvent} ev
         */
        const onPointerOut = (ev) => {
            if (trackGroups) {
                const group = closestGroupOf(ev.target);
                if (group && group !== closestGroupOf(ev.relatedTarget)) {
                    onGroupPointerLeave(group);
                }
            }
            const element = closestElementOf(ev.target);
            if (element && element !== closestElementOf(ev.relatedTarget)) {
                onElementLeave(element, ev.relatedTarget);
            }
        };

        addListener(ref.el, "pointerover", onPointerOver);
        addListener(ref.el, "pointerout", onPointerOut);

        current.element.after(current.placeHolder);

        return pick(current, "element", "group");
    },
    onDrag(/** @type {{ ctx: Record<string, any> }} */ { ctx }) {
        ctx.haveAlreadyChanged = false;
    },
    onDragEnd(/** @type {{ ctx: Record<string, any> }} */ { ctx }) {
        return pick(ctx.current, "element", "group");
    },
    onDrop(/** @type {{ ctx: Record<string, any> }} */ { ctx }) {
        const { current, groupSelector } = ctx;
        const previous = current.placeHolder.previousElementSibling;
        const next = current.placeHolder.nextElementSibling;
        if (previous !== current.element && next !== current.element) {
            const element = current.element;
            if (ctx.applyChangeOnDrop) {
                if (previous) {
                    previous.after(element);
                } else if (next) {
                    next.before(element);
                }
            }
            return {
                element,
                group: current.group,
                previous,
                next,
                parent: groupSelector && current.placeHolder.closest(groupSelector),
            };
        }
    },
    onWillStartDrag(
        /** @type {{ ctx: Record<string, any>, addCleanup: Function }} */ {
            ctx,
            addCleanup,
        },
    ) {
        const { connectGroups, current, groupSelector } = ctx;

        if (groupSelector) {
            current.group = current.element.closest(groupSelector);
            if (!connectGroups) {
                current.container = current.group;
            }
        }

        if (ctx.placeholderClone) {
            current.placeHolder = current.element.cloneNode(false);
        } else {
            current.placeHolder = document.createElement("div");
        }
        current.placeHolder.classList.add(...ctx.placeholderClasses);
        current.element.classList.add(...ctx.followingElementClasses);

        addCleanup(() =>
            current.element.classList.remove(...ctx.followingElementClasses),
        );
        addCleanup(() => current.placeHolder.remove());

        return pick(current, "element", "group");
    },
};

/** @type {(params: SortableParams) => SortableState} */
export const useSortable = (/** @type {any} */ sortableParams) => {
    const { setupHooks, ...params } = sortableParams;
    return makeNativeDraggableHook(/** @type {any} */ ({ ...hookParams, setupHooks }))(
        params,
    );
};
