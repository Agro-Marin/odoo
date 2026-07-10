// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_sortable_hook - useSortable wiring for record + group reordering in kanban view */

import { useSortable } from "@web/core/utils/dnd/sortable_owl";

/**
 * @typedef {object} KanbanSortableOptions
 * @property {{ el: HTMLElement | null }} rootRef OWL ref to the kanban root.
 * @property {() => boolean} getCanUseSortable One-time guard (e.g.
 *   ``!env.isSmall``); when false, no sortable listeners are installed.
 * @property {() => boolean} getCanResequenceRecords Per-call gate from
 *   {@link useSortable} for the record-drag instance.
 * @property {() => boolean} getCanResequenceGroups Per-call gate for
 *   the group-drag instance.
 * @property {() => boolean} getCanMoveRecords Whether records can cross
 *   column boundaries; forwarded to ``useSortable``'s ``connectGroups``.
 * @property {() => boolean} getIsGrouped Drives ``useSortable``'s
 *   ``groups`` selector so only grouped kanbans get ``.o_kanban_group``
 *   wired up.
 * @property {() => { length: number; forEach: (cb: (r: any) => void) => void } | null | undefined}
 *   getSelection Currently-selected records, cleared on drag start so a
 *   multi-select drag only moves the dragged card. May be nullish.
 * @property {(params: any) => any} onSortStart
 * @property {(params: any) => any} onSortStop
 * @property {(params: any) => any} onSortRecordGroupEnter
 * @property {(params: any) => any} onSortRecordGroupLeave
 * @property {(dataRecordId: string, dataGroupId: string | undefined, params: any) => any} onSortRecordDrop
 * @property {(dataGroupId: string, params: any) => any} onSortGroupDrop
 */

/**
 * Wire the two ``useSortable`` instances the kanban renderer needs: one
 * for record drag (with optional cross-group connection), one for
 * column reorder. Both are skipped when ``getCanUseSortable()`` is false.
 *
 * @param {KanbanSortableOptions} options
 */
export function useKanbanSortable(options) {
    if (!options.getCanUseSortable()) {
        return;
    }
    const {
        rootRef,
        getCanResequenceRecords,
        getCanResequenceGroups,
        getCanMoveRecords,
        getIsGrouped,
        getSelection,
        onSortStart,
        onSortStop,
        onSortRecordGroupEnter,
        onSortRecordGroupLeave,
        onSortRecordDrop,
        onSortGroupDrop,
    } = options;

    // Shared by both useSortable instances: onDrop's params carry the drop
    // target but not the source's original data-id, so we capture it here.
    let dataRecordId;
    let dataGroupId;

    useSortable({
        enable: getCanResequenceRecords,
        ref: rootRef,
        elements: ".o_draggable",
        ignore: ".dropdown,select",
        groups: () => getIsGrouped() && ".o_kanban_group",
        connectGroups: getCanMoveRecords,
        cursor: "move",
        placeholderClasses: ["visible", "opacity-50", "my-2"],
        onDragStart: (params) => {
            const { element, group } = params;
            dataRecordId = element.dataset.id;
            dataGroupId = group?.dataset.id;
            // Clear any pre-existing selection so the drag affects only the
            // dragged card, not the whole multi-select.
            const selection = getSelection();
            if (selection?.length) {
                selection.forEach((record) => {
                    record.toggleSelection(false);
                });
            }
            return onSortStart(params);
        },
        onDragEnd: (params) => onSortStop(params),
        onGroupEnter: (params) => onSortRecordGroupEnter(params),
        onGroupLeave: (params) => onSortRecordGroupLeave(params),
        onDrop: (params) => onSortRecordDrop(dataRecordId, dataGroupId, params),
    });

    useSortable({
        enable: getCanResequenceGroups,
        ref: rootRef,
        elements: ".o_group_draggable",
        handle: ".o_column_title",
        cursor: "move",
        onDragStart: (params) => {
            const { element } = params;
            dataGroupId = element.dataset.id;
            return onSortStart(params);
        },
        onDragEnd: (params) => onSortStop(params),
        onDrop: (params) => onSortGroupDrop(dataGroupId, params),
    });
}
