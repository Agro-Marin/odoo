// @ts-check
/** @odoo-module native */

import { localization } from "@web/core/l10n/localization";
import { makeDraggableHook } from "@web/core/utils/dnd/draggable_hook_builder_owl";
import { applyGroupParams } from "@web/core/utils/dnd/draggable_hook_builder_utils";
import { viewOf } from "@web/core/utils/dom/ui";

/** @import { DraggableHandlerParams } from "@web/core/utils/dnd/draggable_hook_builder" */
/**
 * @typedef {DraggableHandlerParams & { group: HTMLElement | null }} NestedSortableHandlerParams
 */

/**
 * @typedef {import("./sortable").SortableParams} NestedSortableParams
 * @property {(HTMLElement) => boolean} [preventDrag]
 * @property {boolean | () => boolean} [nest]
 * @property {string | () => string} [listTagName]
 * @property {number | () => number} [nestInterval]
 * @property {number | () => number} [maxLevels]
 * @property {(DraggableHookContext) => boolean} [isAllowed]
 * @property {boolean} [useElementSize]
 * @property {string[] | (() => string[])} [inertSelectors]
 * @property {(params: MoveParams) => any} [onMove]
 */

/**
 * @typedef MoveParams
 * @property {HTMLElement} element
 * @property {HTMLElement | null} group
 * @property {HTMLElement | null} previous
 * @property {HTMLElement | null} next
 * @property {HTMLElement | null} newGroup
 * @property {HTMLElement | null} parent
 * @property {HTMLElement} placeholder
 */

/**
 * @typedef SortableState
 * @property {boolean} dragging
 */

/**
 * @param {Record<string, any>} ctx
 * @param {Element} node
 * @param {number} [depth=0]
 * @returns {number}
 */
function getDeepestChildLevel(ctx, node, depth = 0) {
    let result = 0;
    const childSelector = `${ctx.listTagName} ${ctx.elementSelector}`;
    for (const childNode of node.querySelectorAll(childSelector)) {
        result = Math.max(getDeepestChildLevel(ctx, childNode, depth + 1), result);
    }
    return depth ? result + 1 : result;
}

/**
 * @param {Record<string, any>} ctx
 * @returns {boolean}
 */
function hasReachedMaxLevel(ctx) {
    if (!ctx.nest || ctx.maxLevels < 1) {
        return false;
    }
    let level = getDeepestChildLevel(ctx, ctx.current.element);
    let list = ctx.current.placeHolder.closest(ctx.listTagName);
    while (list) {
        level++;
        list = list.parentNode.closest(ctx.listTagName);
    }
    return level > ctx.maxLevels;
}

/**
 * @param {Record<string, any>} ctx
 * @returns {boolean}
 */
function isAllowedNodeMove(ctx) {
    return !hasReachedMaxLevel(ctx) && ctx.isAllowed(ctx.current, ctx.elementSelector);
}

/**
 * The element's nested list, created on first use.
 *
 * @param {Record<string, any>} ctx
 * @param {Element} el
 * @returns {HTMLElement}
 */
function childListOf(ctx, el) {
    const existing = el.querySelector(ctx.listTagName);
    if (existing) {
        return /** @type {HTMLElement} */ (existing);
    }
    const list = document.createElement(ctx.listTagName);
    el.appendChild(list);
    return list;
}

/**
 * @param {Record<string, any>} ctx
 * @param {Element} el
 */
function positionOf(ctx, el) {
    return {
        previous: el.previousElementSibling,
        next: el.nextElementSibling,
        parent: el.parentElement?.closest(ctx.elementSelector) || null,
        group: ctx.groupSelector ? el.closest(ctx.groupSelector) : false,
    };
}

/**
 * The placeholder just moved: hide it where the move is refused, bounce it
 * back out where it would nest too deep, and otherwise tell the consumer.
 *
 * @param {Record<string, any>} ctx
 * @param {Function} callHandler
 * @param {Record<string, any>} prevPos
 */
function notifyMove(ctx, callHandler, prevPos) {
    const { placeHolder } = ctx.current;
    if (!ctx.isAllowed(ctx.current, ctx.elementSelector)) {
        placeHolder.classList.add("d-none");
        return;
    } else if (hasReachedMaxLevel(ctx)) {
        const previousSiblingEl = placeHolder
            .closest(ctx.listTagName)
            .closest(ctx.elementSelector);
        previousSiblingEl.after(placeHolder);
        return;
    }
    placeHolder.classList.remove("d-none");
    callHandler("onMove", {
        element: ctx.current.element,
        previous: placeHolder.previousElementSibling,
        next: placeHolder.nextElementSibling,
        parent: ctx.nest
            ? placeHolder.parentElement.closest(ctx.elementSelector)
            : false,
        group: ctx.currentGroup,
        newGroup: ctx.connectGroups
            ? placeHolder.closest(ctx.groupSelector)
            : ctx.currentGroup,
        prevPos,
        placeholder: placeHolder,
    });
}

/**
 * Horizontal travel past the nest interval moves the placeholder one level
 * out (away from the list's leading edge) or one level in (under its
 * previous sibling).
 *
 * @param {Record<string, any>} ctx
 * @param {Function} callHandler
 * @param {Record<string, any>} position
 * @returns {boolean} whether the travel consumed this move
 */
function nestHorizontally(ctx, callHandler, position) {
    const xInterval = ctx.prevNestX - ctx.pointer.x;
    if (ctx.nestInterval - (-1) ** ctx.isRTL * xInterval < 1) {
        let nextElement = position.next;
        if (nextElement === ctx.current.element) {
            nextElement = ctx.current.element.nextElementSibling;
        }
        if (!nextElement) {
            const newSibling = position.parent;
            if (newSibling) {
                newSibling.after(ctx.current.placeHolder);
                notifyMove(ctx, callHandler, position);
            }
        }
        ctx.prevNestX = ctx.pointer.x;
        return true;
    } else if (ctx.nestInterval + (-1) ** ctx.isRTL * xInterval < 1) {
        let parent = position.previous;
        if (parent === ctx.current.element) {
            parent = ctx.current.element.previousElementSibling;
        }
        if (parent?.matches(ctx.elementSelector)) {
            childListOf(ctx, parent).appendChild(ctx.current.placeHolder);
            notifyMove(ctx, callHandler, position);
        }
        ctx.prevNestX = ctx.pointer.x;
        return true;
    }
    return false;
}

/**
 * The pointer is over a sortable element: the placeholder goes before it
 * near its top edge, after it (or into its children) lower down.
 *
 * @param {Record<string, any>} ctx
 * @param {Function} callHandler
 * @param {Element} element
 * @param {Record<string, any>} position
 * @param {number} currentTop
 */
function placeAroundElement(ctx, callHandler, element, position, currentTop) {
    const elementPosition = positionOf(ctx, element);
    const eRect = element.getBoundingClientRect();
    const pos = ctx.current.placeHolder.compareDocumentPosition(element);
    if (currentTop - eRect.y < 10) {
        if (
            pos & Node.DOCUMENT_POSITION_PRECEDING &&
            (ctx.nest || elementPosition.parent === position.parent)
        ) {
            element.before(ctx.current.placeHolder);
            notifyMove(ctx, callHandler, position);
            ctx.prevNestX = ctx.pointer.x;
        }
    } else if (currentTop - eRect.y > 15 && pos === Node.DOCUMENT_POSITION_FOLLOWING) {
        if (ctx.nest) {
            const elementChildList = childListOf(ctx, element);
            if (elementChildList.querySelector(ctx.elementSelector)) {
                elementChildList.prepend(ctx.current.placeHolder);
            } else {
                element.after(ctx.current.placeHolder);
            }
            notifyMove(ctx, callHandler, position);
            ctx.prevNestX = ctx.pointer.x;
        } else if (elementPosition.parent === position.parent) {
            element.after(ctx.current.placeHolder);
            notifyMove(ctx, callHandler, position);
        }
    }
}

/**
 * The pointer is over another group's empty space: the placeholder joins
 * that group at the end nearest to where it came from.
 *
 * @param {Record<string, any>} ctx
 * @param {Function} callHandler
 * @param {Element} closestEl
 * @param {Record<string, any>} position
 */
function moveIntoGroup(ctx, callHandler, closestEl, position) {
    const group = closestEl.closest(ctx.groupSelector);
    if (!group || group === position.group || !(ctx.nest || !position.parent)) {
        return;
    }
    if (!position.group) {
        return;
    }
    const list = childListOf(ctx, group);
    if (
        group.compareDocumentPosition(position.group) ===
        Node.DOCUMENT_POSITION_PRECEDING
    ) {
        list.prepend(ctx.current.placeHolder);
    } else {
        list.appendChild(ctx.current.placeHolder);
    }
    notifyMove(ctx, callHandler, position);
    ctx.prevNestX = ctx.pointer.x;
    callHandler("onGroupEnter", { group, placeholder: ctx.current.placeHolder });
    callHandler("onGroupLeave", {
        group: position.group,
        placeholder: ctx.current.placeHolder,
    });
}

/** @type {(params: NestedSortableParams) => SortableState} */
export const useNestedSortable = /** @type {any} */ (
    makeDraggableHook(
        /** @type {any} */ ({
            name: "useNestedSortable",
            acceptedParams: {
                groups: [String, Function],
                connectGroups: [Boolean, Function],
                nest: [Boolean],
                listTagName: [String],
                nestInterval: [Number],
                maxLevels: [Number],
                isAllowed: [Function],
                useElementSize: [Boolean],
                inertSelectors: [Object, Function],
            },
            defaultParams: {
                connectGroups: false,
                currentGroup: null,
                cursor: "grabbing",
                edgeScrolling: { speed: 20, threshold: 60 },
                elements: "li",
                groupSelector: null,
                nest: false,
                listTagName: "ul",
                nestInterval: 15,
                maxLevels: 0,
                isAllowed: (/** @type {Record<string, any>} */ ctx) => true,
                useElementSize: false,
                inertSelectors: [".o_navbar", ".o_action_manager"],
            },

            onComputeParams(
                /** @type {{ ctx: Record<string, any>, params: Record<string, any> }} */ {
                    ctx,
                    params,
                },
            ) {
                applyGroupParams(ctx, params);
                ctx.nest = params.nest;
                ctx.listTagName = params.listTagName;
                ctx.nestInterval = params.nestInterval;
                ctx.isRTL = localization.direction === "rtl";
                ctx.maxLevels = params.maxLevels || 0;
                ctx.isAllowed = params.isAllowed ?? (() => true);
                ctx.useElementSize = params.useElementSize;
                ctx.inertSelectors = params.inertSelectors ?? [];
            },

            onWillStartDrag(
                /** @type {{ ctx: Record<string, any>, addCleanup: Function }} */ {
                    ctx,
                    addCleanup,
                },
            ) {
                if (ctx.groupSelector) {
                    ctx.currentGroup = ctx.current.element.closest(ctx.groupSelector);
                    if (!ctx.connectGroups) {
                        ctx.current.container = ctx.currentGroup;
                    }
                }

                if (ctx.nest) {
                    ctx.prevNestX = ctx.pointer.x;
                }
                ctx.current.placeHolder = ctx.current.element.cloneNode(false);
                ctx.current.placeHolder.removeAttribute("id");
                ctx.current.placeHolder.classList.add("w-100", "d-block");
                if (ctx.useElementSize) {
                    ctx.current.placeHolder.style.height = viewOf(
                        ctx.current.element,
                    ).getComputedStyle(ctx.current.element).height;
                    ctx.current.placeHolder.classList.add(
                        "o_nested_sortable_placeholder_realsize",
                    );
                } else {
                    ctx.current.placeHolder.classList.add(
                        "o_nested_sortable_placeholder",
                    );
                }
                addCleanup(() => ctx.current.placeHolder.remove());
            },

            onDragStart(
                /** @type {{ ctx: Record<string, any>, addStyle: Function }} */ {
                    ctx,
                    addStyle,
                },
            ) {
                ctx.selectorX = ctx.isRTL
                    ? ctx.current.elementRect.left + 1
                    : ctx.current.elementRect.right - 1;

                ctx.current.element.after(ctx.current.placeHolder);
                addStyle(ctx.current.element, { opacity: 0.5 });

                addStyle(document.body, { "pointer-events": "auto" });
                for (const selector of ctx.inertSelectors) {
                    addStyle(document.querySelector(selector), {
                        "pointer-events": "none",
                    });
                }
                addStyle(ctx.current.container, { "pointer-events": "auto" });

                return {
                    element: ctx.current.element,
                    group: ctx.currentGroup,
                };
            },
            onDrag(
                /** @type {{ ctx: Record<string, any>, callHandler: Function }} */ {
                    ctx,
                    callHandler,
                },
            ) {
                const position = positionOf(ctx, ctx.current.placeHolder);
                if (ctx.nest && nestHorizontally(ctx, callHandler, position)) {
                    return;
                }
                const currentTop = ctx.pointer.y - ctx.current.offset.y;
                const closestEl = document.elementFromPoint(ctx.selectorX, currentTop);
                if (!closestEl) {
                    return;
                }
                const element = closestEl.closest(ctx.elementSelector);
                if (element && element !== ctx.current.placeHolder) {
                    placeAroundElement(ctx, callHandler, element, position, currentTop);
                } else {
                    moveIntoGroup(ctx, callHandler, closestEl, position);
                }
            },
            onDrop(/** @type {{ ctx: Record<string, any> }} */ { ctx }) {
                if (!isAllowedNodeMove(ctx)) {
                    return;
                }
                const previous = ctx.current.placeHolder.previousElementSibling;
                const next = ctx.current.placeHolder.nextElementSibling;
                if (previous !== ctx.current.element && next !== ctx.current.element) {
                    return {
                        element: ctx.current.element,
                        group: ctx.currentGroup,
                        previous,
                        next,
                        newGroup:
                            ctx.groupSelector &&
                            ctx.current.placeHolder.closest(ctx.groupSelector),
                        parent: ctx.current.placeHolder.parentElement.closest(
                            ctx.elementSelector,
                        ),
                        placeholder: ctx.current.placeHolder,
                    };
                }
            },
            onDragEnd(/** @type {{ ctx: Record<string, any> }} */ { ctx }) {
                return {
                    element: ctx.current.element,
                    group: ctx.currentGroup,
                };
            },
        }),
    )
);
