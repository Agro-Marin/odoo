// @ts-check
/** @odoo-module native */

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
 * @param {{ parent: HTMLElement, element: HTMLElement, next: HTMLElement | null, previous: HTMLElement | null }} drop
 * @param {() => Array<{ name: string; elements: Array<{ name: string }> }>} getGroupedPropertiesList
 * @returns {{ to: string | null, moveBefore: boolean }}
 */
function resolveDropTarget({ parent, next, previous }, getGroupedPropertiesList) {
    const afterPrevious = previous?.getAttribute("property-name");
    if (afterPrevious) {
        return { to: afterPrevious, moveBefore: false };
    }
    if (next) {
        const sibling = next.classList.contains("o_field_property_group_label")
            ? next.closest(".o_property_group")
            : next;
        const to = sibling.getAttribute("property-name");
        if (to) {
            return { to, moveBefore: true };
        }
    }
    const groupName = parent.getAttribute("property-name");
    const group = getGroupedPropertiesList().find((g) => g.name === groupName);
    if (!group) {
        return { to: null, moveBefore: false };
    }
    return {
        to: group.elements.length ? group.elements.at(-1).name : groupName,
        moveBefore: false,
    };
}

/**
 * @param {PropertiesSortableOptions} options
 */
function useSortableProperties(options) {
    const { propertiesRef, getEnabled, getRenderedColumnsCount } = options;
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
        onDrop: async (drop) => {
            const { to, moveBefore } = resolveDropTarget(
                drop,
                options.getGroupedPropertiesList,
            );
            await options.onPropertyMoveTo(
                drop.element.getAttribute("property-name"),
                to,
                moveBefore,
            );
        },
        onDragEnd: ({ element }) => {
            propertiesRef.el.classList.remove("o_property_dragging");
            element.classList.remove("o_property_drag_item");
            propertiesRef.el
                .querySelector(".o_property_drag_group")
                ?.classList.remove("o_property_drag_group");
        },
        onGroupEnter: ({ group }) => {
            group.classList.add("o_property_drag_group");
            options.onToggleSeparators([group.getAttribute("property-name")], false);
        },
        onGroupLeave: ({ group }) => {
            group.classList.remove("o_property_drag_group");
        },
    });
}

/**
 * @param {PropertiesSortableOptions} options
 */
function useSortableGroups({ propertiesRef, getEnabled, onGroupMoveTo }) {
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
        onDrop: async ({ element, previous }) =>
            onGroupMoveTo(
                element.getAttribute("property-name"),
                previous?.getAttribute("property-name"),
            ),
        onDragEnd: ({ element }) => {
            propertiesRef.el.classList.remove("o_property_dragging");
            element.classList.remove("o_property_drag_item");
        },
    });
}

/**
 * @param {PropertiesSortableOptions} options
 */
export function usePropertiesSortable(options) {
    useSortableProperties(options);
    useSortableGroups(options);
}
