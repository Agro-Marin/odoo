// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/properties_sortable_hook - useSortable wiring for property + property-group drag in the properties field */

import { useSortable } from "@web/core/utils/dnd/sortable_owl";

/**
 * @typedef {object} PropertiesSortableOptions
 * @property {{ el: HTMLElement | null }} propertiesRef OWL ref to the
 *   properties root container.
 * @property {() => boolean} getEnabled Per-call gate forwarded to
 *   ``useSortable.enable``. Typically
 *   ``!readonly && state.canChangeDefinition``.
 * @property {() => number} getRenderedColumnsCount Column count for
 *   the active layout. Mono-column (``1``) widens the draggable
 *   selector to include group-label rows so the user can drop a
 *   property right above a separator.
 * @property {() => Array<{ name: string; elements: Array<{ name: string }> }>}
 *   getGroupedPropertiesList Lookup used when a drop lands in an empty
 *   group: we walk to the group's last child to compute the ``to``
 *   anchor for {@link onPropertyMoveTo}.
 * @property {(from: string, to: string | null, moveBefore: boolean) => Promise<void>}
 *   onPropertyMoveTo Renderer-supplied move handler.
 * @property {(from: string, to: string | undefined) => Promise<void>}
 *   onGroupMoveTo Renderer-supplied group-move handler.
 * @property {(separatorNames: string[], forceState: boolean) => void}
 *   onToggleSeparators Renderer-supplied separator visibility toggle.
 */

/**
 * Install the two ``useSortable`` instances the properties field
 * needs: one for individual properties (with optional cross-group
 * connection) and one for property groups (column-style reordering).
 *
 * Both instances share the same ``enable`` predicate and the same
 * dragging-class bookkeeping, but their selectors and drop handlers
 * differ — bundling them in one hook keeps the wiring near the
 * shared drag-state classes (``o_property_dragging``,
 * ``o_property_drag_item``, ``o_property_drag_group``).
 *
 * @param {PropertiesSortableOptions} options
 */
export function usePropertiesSortable(options) {
    const {
        propertiesRef,
        getEnabled,
        getRenderedColumnsCount,
        getGroupedPropertiesList,
        onPropertyMoveTo,
        onGroupMoveTo,
        onToggleSeparators,
    } = options;

    // Individual property drag — optionally crosses group boundaries
    // so the user can move a property between columns / sections.
    useSortable({
        enable: getEnabled,
        ref: propertiesRef,
        handle: ".o_field_property_label .oi-draggable",
        // On mono-column layout we also accept group labels as drop
        // anchors so the user can drop a property right above a
        // separator — a common mono-column UX pattern. Multi-column
        // keeps the selector tight on actual property nodes.
        elements:
            getRenderedColumnsCount() === 1
                ? "*:is(.o_property_field, .o_field_property_group_label)"
                : ".o_property_field",
        groups: ".o_property_group",
        connectGroups: true,
        cursor: "grabbing",
        onDragStart: ({ element, group }) => {
            propertiesRef.el.classList.add("o_property_dragging");
            element.classList.add("o_property_drag_item");
            group.classList.add("o_property_drag_group");
            // Blur whatever input the user was editing — without this
            // an in-flight ``char`` edit would write back as the drag
            // settles and clobber the new position's value.
            /** @type {HTMLElement} */ (document.activeElement).blur();
        },
        onDrop: async ({ parent, element, next, previous }) => {
            const from = element.getAttribute("property-name");
            let to = previous?.getAttribute("property-name");
            let moveBefore = false;
            if (!to && next) {
                // The drop sits at the start of a group / column. The
                // ``next`` sibling tells us the anchor; mono-column
                // shifts to the parent ``.o_property_group`` so we
                // pin to the group's own name.
                if (next.classList.contains("o_field_property_group_label")) {
                    next = next.closest(".o_property_group");
                }
                to = next.getAttribute("property-name");
                moveBefore = !!to;
            }
            if (!to) {
                // Drop into an empty group, or somewhere ``next`` /
                // ``previous`` couldn't anchor — walk the
                // groupedPropertiesList to find the group's last
                // child, or pin to the group name itself when empty.
                const groupName = parent.getAttribute("property-name");
                const group = /** @type {any} */ (
                    getGroupedPropertiesList().find((g) => g.name === groupName)
                );
                if (!group) {
                    to = null;
                    moveBefore = false;
                } else {
                    to = group.elements.length ? group.elements.at(-1).name : groupName;
                }
            }
            await onPropertyMoveTo(from, to, moveBefore);
        },
        onDragEnd: ({ element }) => {
            propertiesRef.el.classList.remove("o_property_dragging");
            element.classList.remove("o_property_drag_item");
            const targetGroup = propertiesRef.el.querySelector(
                ".o_property_drag_group",
            );
            if (targetGroup) {
                targetGroup.classList.remove("o_property_drag_group");
            }
        },
        onGroupEnter: ({ group }) => {
            group.classList.add("o_property_drag_group");
            onToggleSeparators([group.getAttribute("property-name")], false);
        },
        onGroupLeave: ({ group }) => {
            group.classList.remove("o_property_drag_group");
        },
    });

    // Group-level drag — reorder whole property groups (columns).
    // Selector excludes the empty-name group ("the implicit ungrouped
    // bucket") since reordering it has no semantic meaning.
    useSortable({
        enable: getEnabled,
        ref: propertiesRef,
        handle: ".o_field_property_group_label .oi-draggable",
        elements: ".o_property_group:not([property-name=''])",
        cursor: "grabbing",
        onDragStart: ({ element }) => {
            propertiesRef.el.classList.add("o_property_dragging");
            element.classList.add("o_property_drag_item");
            /** @type {HTMLElement} */ (document.activeElement).blur();
        },
        onDrop: async ({ element, previous }) => {
            const from = element.getAttribute("property-name");
            const to = previous?.getAttribute("property-name");
            await onGroupMoveTo(from, to);
        },
        onDragEnd: ({ element }) => {
            propertiesRef.el.classList.remove("o_property_dragging");
            element.classList.remove("o_property_drag_item");
        },
    });
}
