// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dnd/sortable - useSortable hook for reordering elements within and across groups */

import { pick } from "@web/core/utils/collections/objects";
import {
    DRAGGED_CLASS,
    makeDraggableHook as nativeMakeDraggableHook,
} from "@web/core/utils/dnd/draggable_hook_builder";

/** @import { DraggableHandlerParams } from "@web/core/utils/dnd/draggable_hook_builder" */
/** @typedef {DraggableHandlerParams & { group: HTMLElement | null }} SortableHandlerParams */

/**
 * @typedef SortableParams
 *
 * MANDATORY
 *
 * @property {{ el: HTMLElement | null }} ref
 * @property {string} elements defines sortable elements
 *
 * OPTIONAL
 *
 * @property {boolean | (() => boolean)} [enable] whether the sortable system should
 *  be enabled.
 * @property {number} [delay] delay before starting a sequence after a "pointerdown".
 * @property {number} [touchDelay] same as "delay", but specific to touch environments.
 * @property {string | (() => string)} [groups] defines parent groups of sortable
 *  elements, enabling `onGroupEnter`/`onGroupLeave` callbacks.
 * @property {string | (() => string)} [handle] additional selector for when the
 *  dragging sequence must be initiated when dragging on a certain part of the element.
 * @property {string | (() => string)} [ignore] selector targetting elements that
 *  must initiate a drag.
 * @property {boolean | (() => boolean)} [connectGroups] whether elements can be
 *  dragged accross different parent groups. Note that it requires a `groups` param to work.
 * @property {string | (() => string)} [cursor] cursor style during the dragging
 *  sequence.
 * @property {boolean} [clone] the placeholder is a clone of the drag element.
 * @property {string[]} [placeholderClasses] array of classes added to the placeholder
 *  element.
 * @property {boolean} [applyChangeOnDrop] on drop the change is applied to the DOM.
 * @property {string[]} [followingElementClasses] array of classes added to the
 *  element that follow the pointer.
 *
 * HANDLERS (also optional)
 *
 * @property {(params: SortableHandlerParams) => any} [onDragStart]
 *  called when a dragging sequence is initiated.
 * @property {(params: DraggableHandlerParams) => any} [onElementEnter] called when
 *  the cursor enters another sortable element.
 * @property {(params: DraggableHandlerParams) => any} [onElementLeave] called when
 *  the cursor leaves another sortable element.
 * @property {(params: SortableHandlerParams) => any} [onGroupEnter] (if a `groups`
 *  is specified): will be called when the cursor enters another group element.
 * @property {(params: SortableHandlerParams) => any} [onGroupLeave] (if a `groups`
 *  is specified): will be called when the cursor leaves another group element.
 * @property {(params: SortableHandlerParams) => any} [onDragEnd]
 *  called when the dragging sequence ends, regardless of the reason.
 * @property {(params: DropParams) => any} [onDrop] called on pointerup when the
 *  dragged element has moved elsewhere (@see DropParams).
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

    // Build steps
    onComputeParams(
        /** @type {{ ctx: Record<string, any>, params: Record<string, any> }} */ {
            ctx,
            params,
        },
    ) {
        // Group selector
        ctx.groupSelector = params.groups || null;
        if (ctx.groupSelector) {
            ctx.fullSelector = [ctx.groupSelector, ctx.fullSelector].join(" ");
        }

        // Connection accross groups
        ctx.connectGroups = params.connectGroups;

        ctx.placeholderClone = params.clone;
        ctx.placeholderClasses = params.placeholderClasses;
        ctx.applyChangeOnDrop = params.applyChangeOnDrop;
        ctx.followingElementClasses = params.followingElementClasses;
    },

    // Runtime steps
    onDragStart(
        /** @type {{ ctx: Record<string, any>, addListener: Function, addStyle: Function, callHandler: Function }} */ {
            ctx,
            addListener,
            addStyle,
            callHandler,
        },
    ) {
        const { connectGroups, current, elementSelector, groupSelector, ref } = ctx;

        /**
         * Called when the cursor enters another sortable element.
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
         * Called when the cursor leaves another sortable element.
         * @param {HTMLElement} element
         */
        const onElementPointerLeave = (element) => {
            callHandler("onElementLeave", { element });
        };

        /**
         * Same as {@link onElementPointerEnter}, in complex (non-clone)
         * placeholder mode.
         * @param {HTMLElement} element
         */
        const onElementComplexPointerEnter = (element) => {
            if (ctx.haveAlreadyChanged) {
                return;
            }
            const siblingArray = [
                // The dragged/target item is always attached to its list here.
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
         * Same as {@link onElementPointerLeave}, in complex (non-clone)
         * placeholder mode.
         * @param {HTMLElement} element
         * @param {EventTarget | null} relatedTarget
         */
        const onElementComplexPointerLeave = (element, relatedTarget) => {
            if (ctx.haveAlreadyChanged) {
                return;
            }
            const relatedElement = /** @type {HTMLElement} */ (relatedTarget);
            if (!relatedElement) {
                // Pointer left the browser window — no sibling comparison possible.
                return;
            }
            const elementRect = element.getBoundingClientRect();
            const relatedElementRect = relatedElement.getBoundingClientRect();

            const siblingArray = [
                // The dragged/target item is always attached to its list here.
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
         * Called when the cursor enters another group element.
         * @param {HTMLElement} group
         */
        const onGroupPointerEnter = (group) => {
            group.appendChild(current.placeHolder);
            callHandler("onGroupEnter", { group });
        };

        /**
         * Called when the cursor leaves another group element.
         * @param {HTMLElement} group
         */
        const onGroupPointerLeave = (group) => {
            callHandler("onGroupLeave", { group });
        };

        if (ctx.placeholderClone) {
            const { width, height } = current.elementRect;

            // Adjusts size for the placeholder element
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
         * Resolves the sortable element containing the given event target:
         * the same elements the previous per-element listeners were bound on
         * (inside the ref, and neither the dragged element nor the
         * placeholder).
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
         * Resolves the group element containing the given event target.
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

        // Group transitions are only tracked if the elements are not confined
        // to their parents and a 'groupSelector' has been provided.
        const trackGroups = Boolean(connectGroups && groupSelector);

        /**
         * Delegated "pointerover" event handler: dispatches group and element
         * "enter" transitions by comparing the sortable group/element under
         * the pointer with the one it comes from ("relatedTarget"), emulating
         * the "pointerenter" semantics of the previous per-element listeners.
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
         * Delegated "pointerout" event handler: dispatches group and element
         * "leave" transitions (@see onPointerOver).
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

        // A single delegated "pointerover"/"pointerout" pair replaces the
        // previous per-element/per-group "pointerenter"/"pointerleave"
        // listeners, avoiding O(N) listener additions and O(N) inline
        // "pointer-events: auto" writes per drag start. `addListener`
        // restores pointer events on the whole ref subtree via one
        // container-level style, needed since the body is "pe-none" during
        // the drag sequence.
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
                // Apply to the DOM the result of sortable()
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
    const { setupHooks } = sortableParams;
    delete sortableParams.setupHooks;
    return nativeMakeDraggableHook(/** @type {any} */ ({ ...hookParams, setupHooks }))(
        sortableParams,
    );
};
