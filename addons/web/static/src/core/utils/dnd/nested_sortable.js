// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/dnd/nested_sortable - useNestedSortable OWL hook for drag-and-drop with hierarchical nesting */

import { localization } from "@web/core/l10n/localization";
import { makeDraggableHook } from "@web/core/utils/dnd/draggable_hook_builder_owl";

/** @import { DraggableHandlerParams } from "@web/core/utils/dnd/draggable_hook_builder" */
/** @typedef {DraggableHandlerParams & { group: HTMLElement | null }} NestedSortableHandlerParams */

/**
 * @typedef {import("./sortable").SortableParams} NestedSortableParams
 *
 * OPTIONAL
 *
 * @property {(HTMLElement) => boolean} [preventDrag] function receiving a
 *  the current target for dragging (element) and returning a boolean, whether
 *  the element can be effectively dragged or not.
 * @property {boolean | () => boolean} [nest] whether elements are nested or not.
 * @property {string | () => string} [listTagName] type of lists ("ul" or "ol").
 * @property {number | () => number} [nestInterval] Horizontal distance needed to trigger
 * a change in the list hierarchy (i.e. changing parent when moving horizontally)
 * @property {number | () => number} [maxLevels] The maximum depth of nested items
 * the list can accept. If set to '0' the levels are unlimited. Default: 0
 * @property {(DraggableHookContext) => boolean} [isAllowed] You can specify a custom function
 * to verify if a drop location is allowed. return True by default
 * @property {boolean} [useElementSize] The placeholder use the dragged element size instead
 * of the small 8px lines. Default:false
 * @property {string[] | (() => string[])} [inertSelectors] selectors of the elements that
 * must be made inert (pointer-events: none) during a drag sequence, so the drag cursor is
 * shown across the whole screen while those zones stay non-interactive. Defaults to the
 * webclient chrome (`.o_navbar`, `.o_action_manager`); non-webclient embeddings should pass
 * their own zones (or `[]`) rather than relying on these layout-specific selectors.
 *
 * HANDLERS (also optional)
 *
 * @property {(params: MoveParams) => any} [onMove] called when the element has moved
 * (changed position) (@see MoveParams).
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

            // Set the parameters.
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
                // Connection across groups
                ctx.connectGroups = params.connectGroups;
                // Nested elements
                ctx.nest = params.nest;
                // List tag name
                ctx.listTagName = params.listTagName;
                // Horizontal distance needed to trigger a change in the list hierarchy
                // (i.e. changing parent when moving horizontally)
                ctx.nestInterval = params.nestInterval;
                ctx.isRTL = localization.direction === "rtl";
                ctx.maxLevels = params.maxLevels || 0;
                ctx.isAllowed = params.isAllowed ?? (() => true);
                ctx.useElementSize = params.useElementSize;
                // Zones made inert during the drag. Kept as a param so this
                // core util does not hardcode a dependency on the webclient
                // layout (see the `inertSelectors` typedef).
                ctx.inertSelectors = params.inertSelectors ?? [];
            },

            // Set the current group and create the placeholder row that will take the
            // place of the moving row.
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
                    ctx.current.placeHolder.style.height = getComputedStyle(
                        ctx.current.element,
                    ).height;
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

            // Make the placeholder take the place of the moving row, and add style on
            // different elements to provide feedback that there is an ongoing dragging
            // sequence.
            onDragStart(
                /** @type {{ ctx: Record<string, any>, addStyle: Function }} */ {
                    ctx,
                    addStyle,
                },
            ) {
                // Horizontal position which will be used to detect row changes when moving vertically, so that
                // we do not need to be on the row to trigger row changes (only the vertical position matters).
                // Nested rows are shorter than "root" rows, and do not start at the same horizontal position.
                // However, every row ends at the same horizontal position. Therefore, we use the end of the
                // current element - 1 as horizontal position.
                ctx.selectorX = ctx.isRTL
                    ? ctx.current.elementRect.left + 1
                    : ctx.current.elementRect.right - 1;

                // Placeholder is initially added right after the current element.
                ctx.current.element.after(ctx.current.placeHolder);
                addStyle(ctx.current.element, { opacity: 0.5 });

                // Remove pointer-events style added by draggable_hook_builder and set
                // it on the view elements instead as in our case we want to show the
                // ctx.cursor style on the whole screen, not only in the ref el.
                addStyle(document.body, { "pointer-events": "auto" });
                // Make the caller-provided inert zones non-interactive. These
                // default to the webclient chrome but are configurable so core
                // does not depend on a specific layout; unmatched selectors are
                // simply skipped (addStyle is a no-op on null).
                for (const selector of ctx.inertSelectors) {
                    addStyle(document.querySelector(selector), {
                        "pointer-events": "none",
                    });
                }
                addStyle(ctx.current.container, { "pointer-events": "auto" });

                // Calls "onDragStart" handler
                return {
                    element: ctx.current.element,
                    group: ctx.currentGroup,
                };
            },
            _getDeepestChildLevel(
                /** @type {Record<string, any>} */ ctx,
                /** @type {Element} */ node,
                depth = 0,
            ) {
                let result = 0;
                const childSelector = `${ctx.listTagName} ${ctx.elementSelector}`;
                for (const childNode of node.querySelectorAll(childSelector)) {
                    result = Math.max(
                        this._getDeepestChildLevel(ctx, childNode, depth + 1),
                        result,
                    );
                }
                return depth ? result + 1 : result;
            },
            _hasReachMaxAllowedLevel(/** @type {Record<string, any>} */ ctx) {
                if (!ctx.nest || ctx.maxLevels < 1) {
                    return false;
                }
                let level = this._getDeepestChildLevel(ctx, ctx.current.element);
                let list = ctx.current.placeHolder.closest(ctx.listTagName);
                while (list) {
                    level++;
                    list = list.parentNode.closest(ctx.listTagName);
                }
                return level > ctx.maxLevels;
            },
            _isAllowedNodeMove(/** @type {Record<string, any>} */ ctx) {
                return (
                    !this._hasReachMaxAllowedLevel(ctx) &&
                    ctx.isAllowed(ctx.current, ctx.elementSelector)
                );
            },
            // Check if the cursor moved enough to trigger a move. If it did, move the
            // placeholder accordingly.
            onDrag(
                /** @type {{ ctx: Record<string, any>, callHandler: Function }} */ {
                    ctx,
                    callHandler,
                },
            ) {
                const onMove = (/** @type {Record<string, any>} */ prevPos) => {
                    if (!ctx.isAllowed(ctx.current, ctx.elementSelector)) {
                        ctx.current.placeHolder.classList.add("d-none");
                        return;
                    } else if (this._hasReachMaxAllowedLevel(ctx)) {
                        // If the placeholder has reached its max allowed level, it is
                        // moved back to its previous position.
                        const previousSiblingEl = ctx.current.placeHolder
                            .closest(ctx.listTagName)
                            .closest(ctx.elementSelector);
                        previousSiblingEl.after(ctx.current.placeHolder);
                        return;
                    }
                    ctx.current.placeHolder.classList.remove("d-none");
                    callHandler("onMove", {
                        element: ctx.current.element,
                        previous: ctx.current.placeHolder.previousElementSibling,
                        next: ctx.current.placeHolder.nextElementSibling,
                        parent: ctx.nest
                            ? ctx.current.placeHolder.parentElement.closest(
                                  ctx.elementSelector,
                              )
                            : false,
                        group: ctx.currentGroup,
                        newGroup: ctx.connectGroups
                            ? ctx.current.placeHolder.closest(ctx.groupSelector)
                            : ctx.currentGroup,
                        prevPos,
                        placeholder: ctx.current.placeHolder,
                    });
                };
                /**
                 * Get the list element inside an element, or create one if it does not
                 * exists.
                 * @param {HTMLElement} el
                 * @return {HTMLElement} list
                 */
                const getChildList = (/** @type {Element} */ el) => {
                    // The list element is a <ul>/<ol> tag, so the queried match
                    // is an HTMLElement. Split the create path from the lookup
                    // path so neither return reassigns through `Element | null`
                    // (which would defeat flow-narrowing on the later append).
                    const existing = el.querySelector(ctx.listTagName);
                    if (existing) {
                        return /** @type {HTMLElement} */ (existing);
                    }
                    const list = document.createElement(ctx.listTagName);
                    el.appendChild(list);
                    return list;
                };

                const getPosition = (/** @type {Element} */ el) => ({
                    previous: el.previousElementSibling,
                    next: el.nextElementSibling,
                    parent: el.parentElement?.closest(ctx.elementSelector) || null,
                    group: ctx.groupSelector ? el.closest(ctx.groupSelector) : false,
                });
                const position = getPosition(ctx.current.placeHolder);

                /** If nesting elements is allowed, horizontal moves may change the
                 * parent of the placeholder element (the placeholder does not move
                 * above or under an element, but it changes parent):
                 *
                 * - Moving to the left makes the placeholder a child of the previous
                 *   element up in the nested hierarchy, only if the placeholder is the
                 *   last child of its current parent:
                 *
                 *                    Allowed:
                 *    el                           el
                 *     ┣ parent                     ┣ parent
                 *     ┃  ┣ child           -->     ┃  ┗ child
                 *     ┃  ┗ placeholder             ┣ placeholder
                 *     ┗ el                         ┗ el
                 *
                 *                  Not Allowed:
                 *    el                           el
                 *     ┣ parent                     ┣ parent
                 *     ┃  ┣ placeholder     -->     ┣ p┃laceholder   <-- error
                 *     ┃  ┗ child                   ┃  ┗ child
                 *     ┗ el                         ┗ el
                 *
                 *
                 * - Moving to the right makes the placeholder the last child of the
                 * next element down in the nested hierarchy:
                 *
                 *    el                           el
                 *     ┣ parent                    ┣ parent
                 *     ┃  ┗ child           -->    ┃  ┣ child
                 *     ┣ placeholder               ┃  ┗ placeholder
                 *     ┗ el                        ┗ el
                 */
                if (ctx.nest) {
                    const xInterval = ctx.prevNestX - ctx.pointer.x;
                    if (ctx.nestInterval - (-1) ** ctx.isRTL * xInterval < 1) {
                        // Place placeholder after its parent in its parent's list only
                        // if the placeholder is the last child of its parent
                        // (ignoring the current element which is in the dom)
                        let nextElement = position.next;
                        if (nextElement === ctx.current.element) {
                            nextElement = nextElement.nextElementSibling;
                        }
                        if (!nextElement) {
                            const newSibling = position.parent;
                            if (newSibling) {
                                newSibling.after(ctx.current.placeHolder);
                                onMove(position);
                            }
                        }
                        // Recenter the pointer coordinates to this step
                        ctx.prevNestX = ctx.pointer.x;
                        return;
                    } else if (ctx.nestInterval + (-1) ** ctx.isRTL * xInterval < 1) {
                        // Place placeholder as the last child of its previous sibling,
                        // (ignoring the current element which is in the dom)
                        let parent = position.previous;
                        if (parent === ctx.current.element) {
                            parent = parent.previousElementSibling;
                        }
                        if (parent?.matches(ctx.elementSelector)) {
                            getChildList(parent).appendChild(ctx.current.placeHolder);
                            onMove(position);
                        }
                        // Recenter the pointer coordinates to this step
                        ctx.prevNestX = ctx.pointer.x;
                        return;
                    }
                }
                const currentTop = ctx.pointer.y - ctx.current.offset.y;
                const closestEl = document.elementFromPoint(ctx.selectorX, currentTop);
                if (!closestEl) {
                    // Cursor outside of viewport
                    return;
                }
                const element = closestEl.closest(ctx.elementSelector);
                // Vertical moves should move the placeholder element up or down.
                if (element && element !== ctx.current.placeHolder) {
                    const elementPosition = getPosition(element);
                    const eRect = element.getBoundingClientRect();
                    const pos =
                        ctx.current.placeHolder.compareDocumentPosition(element);
                    // Place placeholder before the hovered element in its parent's
                    // list. If the cursor is in the upper part of the element and
                    // if the placeholder is currently after or inside the hovered
                    // element. If the position is not allowed but nesting is allowed,
                    // place the placeholder as the last child of the previous sibling
                    // instead.
                    if (currentTop - eRect.y < 10) {
                        if (
                            pos & Node.DOCUMENT_POSITION_PRECEDING &&
                            (ctx.nest || elementPosition.parent === position.parent)
                        ) {
                            element.before(ctx.current.placeHolder);
                            onMove(position);
                            // Recenter the pointer coordinates to this step
                            ctx.prevNestX = ctx.pointer.x;
                        }
                    } else if (
                        currentTop - eRect.y > 15 &&
                        pos === Node.DOCUMENT_POSITION_FOLLOWING
                    ) {
                        // Place placeholder after the hovered element in its parent's
                        // list if the cursor is not in the upper part of the
                        // element and if the placeholder is currently before the
                        // hovered element.
                        // If nesting is allowed and if the element has at least one
                        // child, place the placeholder above the first child of the
                        // hovered element instead.
                        if (ctx.nest) {
                            const elementChildList = getChildList(element);
                            if (elementChildList.querySelector(ctx.elementSelector)) {
                                elementChildList.prepend(ctx.current.placeHolder);
                                onMove(position);
                            } else {
                                element.after(ctx.current.placeHolder);
                                onMove(position);
                            }
                            // Recenter the pointer coordinates to this step
                            ctx.prevNestX = ctx.pointer.x;
                        } else if (elementPosition.parent === position.parent) {
                            element.after(ctx.current.placeHolder);
                            onMove(position);
                        }
                    }
                } else {
                    const group = closestEl.closest(ctx.groupSelector);
                    if (
                        group &&
                        group !== position.group &&
                        (ctx.nest || !position.parent)
                    ) {
                        if (!position.group) {
                            return;
                        }
                        if (
                            group.compareDocumentPosition(position.group) ===
                            Node.DOCUMENT_POSITION_PRECEDING
                        ) {
                            getChildList(group).prepend(ctx.current.placeHolder);
                            onMove(position);
                        } else {
                            getChildList(group).appendChild(ctx.current.placeHolder);
                            onMove(position);
                        }
                        // Recenter the pointer coordinates to this step
                        ctx.prevNestX = ctx.pointer.x;
                        callHandler("onGroupEnter", {
                            group,
                            placeholder: ctx.current.placeHolder,
                        });
                        callHandler("onGroupLeave", {
                            group: position.group,
                            placeholder: ctx.current.placeHolder,
                        });
                    }
                }
            },
            // If the drop position is different from the starting position, run the
            // onDrop handler from the parameters.
            onDrop(/** @type {{ ctx: Record<string, any> }} */ { ctx }) {
                if (!this._isAllowedNodeMove(ctx)) {
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
            // Run the onDragEnd handler from the parameters.
            onDragEnd(/** @type {{ ctx: Record<string, any> }} */ { ctx }) {
                return {
                    element: ctx.current.element,
                    group: ctx.currentGroup,
                };
            },
        }),
    )
);
