// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/properties_sortable_hook */

import { useSortable } from "@web/core/utils/dnd/sortable_owl";

/**
 * @typedef {object} PropertiesSortableOptions
 * @property {{ el: HTMLElement | null }} propertiesRef
 * @property {() => boolean} getEnabled
 * @property {() => number} getRenderedColumnsCount
 * @property {() => Array<{ name: string; elements: Array<{ name: string }> }>} getGroupedPropertiesList
 * @property {(from: string, to: string | null, moveBefore: boolean) => Promise<void>} onPropertyMoveTo
 * @property {(from: string, to: string | undefined) => Promise<void>} onGroupMoveTo
 * @property {(separatorNames: string[], forceState: boolean) => void} onToggleSeparators
 */

/**
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

    useSortable({
        enable: getEnabled,
        ref: propertiesRef,
        handle: ".o_field_property_label .oi-draggable",
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
            /** @type {HTMLElement} */ (document.activeElement).blur();
        },
        onDrop: async ({ parent, element, next, previous }) => {
            const from = element.getAttribute("property-name");
            let to = previous?.getAttribute("property-name");
            let moveBefore = false;
            if (!to && next) {
                if (next.classList.contains("o_field_property_group_label")) {
                    next = next.closest(".o_property_group");
                }
                to = next.getAttribute("property-name");
                moveBefore = !!to;
            }
            if (!to) {
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
