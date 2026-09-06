// @ts-check
/** @odoo-module native */

import { pick } from "@web/core/utils/collections/objects";
import {
    DRAGGED_CLASS,
    makeNativeDraggableHook,
} from "@web/core/utils/dnd/draggable_hook_builder";
import { applyGroupParams } from "@web/core/utils/dnd/draggable_hook_builder_utils";

/** @import { DraggableHandlerParams } from "@web/core/utils/dnd/draggable_hook_builder" */
/** @typedef {DraggableHandlerParams & { group: HTMLElement | null }} SortableHandlerParams */

/**
 * @typedef SortableParams
 * @property {{ el: HTMLElement | null }} ref
 * @property {string | (() => string)} elements
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
 * @property {(params: SortableHandlerParams) => any} [onWillStartDrag]
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

/**
 * @param {Record<string, any>} ctx
 * @param {HTMLElement} element
 * @returns {boolean}
 */
function acceptsElement(ctx, element) {
    const { connectGroups, current, groupSelector } = ctx;
    return (
        connectGroups ||
        !groupSelector ||
        current.group === element.closest(groupSelector)
    );
}

/**
 * The siblings a placeholder can move among: the placeholder itself and the
 * sortable elements around it, the dragged one excluded.
 *
 * @param {Record<string, any>} ctx
 * @param {HTMLElement} element
 * @returns {Element[]}
 */
function placeholderSiblings(ctx, element) {
    const { current, elementSelector } = ctx;
    return [.../** @type {HTMLElement} */ (element.parentElement).children].filter(
        (el) =>
            el === current.placeHolder ||
            (el.matches(elementSelector) && !el.classList.contains(DRAGGED_CLASS)),
    );
}

/**
 * Cloned placeholder: it takes the dragged element's size, so entering an
 * element is enough to know which side of it the placeholder goes.
 *
 * @param {Record<string, any>} ctx
 * @param {HTMLElement} element
 * @returns {boolean} whether the consumer's onElementEnter fires
 */
function onElementPointerEnter(ctx, element) {
    if (acceptsElement(ctx, element)) {
        const pos = ctx.current.placeHolder.compareDocumentPosition(element);
        if (pos === Node.DOCUMENT_POSITION_PRECEDING) {
            element.before(ctx.current.placeHolder);
        } else if (pos === Node.DOCUMENT_POSITION_FOLLOWING) {
            element.after(ctx.current.placeHolder);
        }
    }
    return true;
}

/**
 * Thin placeholder: crossing a direct sibling swaps with it, crossing a
 * farther one lands the placeholder on the near side, once per pointer move.
 * Once it has moved, later enters of the same pointer move are silent to the
 * consumer as well; that asymmetry with the cloned strategy is preserved.
 *
 * @param {Record<string, any>} ctx
 * @param {HTMLElement} element
 * @returns {boolean} whether the consumer's onElementEnter fires
 */
function onElementComplexPointerEnter(ctx, element) {
    if (ctx.haveAlreadyChanged) {
        return false;
    }
    if (!acceptsElement(ctx, element)) {
        return true;
    }
    const { current } = ctx;
    const siblingArray = placeholderSiblings(ctx, element);
    const isDirectSibling =
        Math.abs(
            siblingArray.indexOf(element) - siblingArray.indexOf(current.placeHolder),
        ) === 1;
    const pos = current.placeHolder.compareDocumentPosition(element);
    const before = isDirectSibling
        ? pos === Node.DOCUMENT_POSITION_PRECEDING
        : pos === Node.DOCUMENT_POSITION_FOLLOWING;
    const after = isDirectSibling
        ? pos === Node.DOCUMENT_POSITION_FOLLOWING
        : pos === Node.DOCUMENT_POSITION_PRECEDING;
    if (before) {
        element.before(current.placeHolder);
        ctx.haveAlreadyChanged = true;
    } else if (after) {
        element.after(current.placeHolder);
        ctx.haveAlreadyChanged = true;
    }
    return true;
}

/**
 * Thin placeholder, leaving the list past its first or last element: the
 * placeholder follows to that end.
 *
 * @param {Record<string, any>} ctx
 * @param {HTMLElement} element
 * @param {EventTarget | null} relatedTarget
 * @returns {boolean} whether the consumer's onElementLeave fires
 */
function onElementComplexPointerLeave(ctx, element, relatedTarget) {
    const relatedElement = /** @type {HTMLElement} */ (relatedTarget);
    if (ctx.haveAlreadyChanged || !relatedElement) {
        return false;
    }
    const { current } = ctx;
    const siblingArray = placeholderSiblings(ctx, element);
    if (siblingArray.includes(relatedElement)) {
        return true;
    }
    const elementRect = element.getBoundingClientRect();
    const relatedElementRect = relatedElement.getBoundingClientRect();
    const elementIndex = siblingArray.indexOf(element);
    const pos = current.placeHolder.compareDocumentPosition(element);
    if (
        elementIndex === 0 &&
        relatedElementRect.top <= elementRect.top &&
        pos === Node.DOCUMENT_POSITION_PRECEDING
    ) {
        element.before(current.placeHolder);
        ctx.haveAlreadyChanged = true;
    } else if (
        elementIndex === siblingArray.length - 1 &&
        relatedElementRect.bottom >= elementRect.bottom &&
        pos === Node.DOCUMENT_POSITION_FOLLOWING
    ) {
        element.after(current.placeHolder);
        ctx.haveAlreadyChanged = true;
    }
    return true;
}

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
        applyGroupParams(ctx, params);

        ctx.placeholderClone = params.clone;
        ctx.placeholderClasses = params.placeholderClasses;
        ctx.applyChangeOnDrop = params.applyChangeOnDrop;
        ctx.followingElementClasses = params.followingElementClasses;
    },

    onDragStart(
        /** @type {{ ctx: Record<string, any>, addListener: Function, addStyle: Function, callHandler: Function }} */ {
            ctx,
            addListener,
            addStyle,
            callHandler,
        },
    ) {
        const { connectGroups, current, elementSelector, groupSelector, ref } = ctx;

        if (ctx.placeholderClone) {
            const { width, height } = current.elementRect;
            addStyle(current.placeHolder, {
                visibility: "hidden",
                display: "block",
                width: `${width}px`,
                height: `${height}px`,
            });
        }

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
                    group.appendChild(current.placeHolder);
                    callHandler("onGroupEnter", { group });
                }
            }
            const element = closestElementOf(ev.target);
            if (element && element !== closestElementOf(ev.relatedTarget)) {
                const notify = ctx.placeholderClone
                    ? onElementPointerEnter(ctx, element)
                    : onElementComplexPointerEnter(ctx, element);
                if (notify) {
                    callHandler("onElementEnter", { element });
                }
            }
        };

        /**
         * @param {PointerEvent} ev
         */
        const onPointerOut = (ev) => {
            if (trackGroups) {
                const group = closestGroupOf(ev.target);
                if (group && group !== closestGroupOf(ev.relatedTarget)) {
                    callHandler("onGroupLeave", { group });
                }
            }
            const element = closestElementOf(ev.target);
            if (element && element !== closestElementOf(ev.relatedTarget)) {
                const notify =
                    ctx.placeholderClone ||
                    onElementComplexPointerLeave(ctx, element, ev.relatedTarget);
                if (notify) {
                    callHandler("onElementLeave", { element });
                }
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
