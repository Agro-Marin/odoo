// @ts-check
/** @odoo-module native */

import { useSortable } from "@web/core/utils/dnd/sortable_owl";

/**
 * @typedef {object} KanbanSortableOptions
 * @property {{ el: HTMLElement | null }} rootRef
 * @property {() => boolean} getCanUseSortable
 * @property {() => boolean} getCanResequenceRecords
 * @property {() => boolean} getCanResequenceGroups
 * @property {() => boolean} getCanMoveRecords
 * @property {() => boolean} getIsGrouped
 * @property {() => { length: number; forEach: (cb: (r: any) => void) => void } | null | undefined} getSelection
 * @property {(params: any) => any} onSortStart
 * @property {(params: any) => any} onSortStop
 * @property {(params: any) => any} onSortRecordGroupEnter
 * @property {(params: any) => any} onSortRecordGroupLeave
 * @property {(dataRecordId: string, dataGroupId: string | undefined, params: any) => any} onSortRecordDrop
 * @property {(dataGroupId: string, params: any) => any} onSortGroupDrop
 */

/**
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

    let dataRecordId;
    let dataGroupId;
    let draggedGroupId;

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
            draggedGroupId = element.dataset.id;
            return onSortStart(params);
        },
        onDragEnd: (params) => onSortStop(params),
        onDrop: (params) => onSortGroupDrop(draggedGroupId, params),
    });
}
