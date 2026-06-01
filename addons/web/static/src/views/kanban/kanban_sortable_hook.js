// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_sortable_hook - useSortable wiring for record + group reordering in kanban view */

import { useSortable } from "@web/core/utils/dnd/sortable_owl";

/**
 * @typedef {object} KanbanSortableOptions
 * @property {{ el: HTMLElement | null }} rootRef OWL ref to the kanban root.
 * @property {() => boolean} getCanUseSortable One-time guard
 *   (e.g. ``!env.isSmall``). When false the hook is a no-op and no
 *   sortable listeners are installed. Checked once at setup time —
 *   mirrors the existing renderer behaviour where touch/mobile builds
 *   skip the drag layer entirely.
 * @property {() => boolean} getCanResequenceRecords Per-call gate
 *   from {@link useSortable} for the record-drag instance. Read on
 *   every drag start.
 * @property {() => boolean} getCanResequenceGroups Per-call gate for
 *   the group-drag instance.
 * @property {() => boolean} getCanMoveRecords Whether records can
 *   cross column boundaries (false locks a record to its current
 *   group). Forwarded to ``useSortable``'s ``connectGroups``.
 * @property {() => boolean} getIsGrouped Drives ``useSortable``'s
 *   ``groups`` selector — only kanbans with columns get the
 *   ``.o_kanban_group`` group-resolver wired up.
 * @property {() => { length: number; forEach: (cb: (r: any) => void) => void } | null | undefined}
 *   getSelection Returns the list of currently-selected records so
 *   ``onDragStart`` can clear them (a multi-select drag picks up
 *   only the dragged card, not the entire selection). May return
 *   nullish if the list has no selection cluster.
 * @property {(params: any) => any} onSortStart
 * @property {(params: any) => any} onSortStop
 * @property {(params: any) => any} onSortRecordGroupEnter
 * @property {(params: any) => any} onSortRecordGroupLeave
 * @property {(dataRecordId: string, dataGroupId: string | undefined, params: any) => any} onSortRecordDrop
 * @property {(dataGroupId: string, params: any) => any} onSortGroupDrop
 */

/**
 * Wire the two ``useSortable`` instances that the kanban renderer
 * needs: one for record drag (with optional cross-group connection),
 * one for column reorder.
 *
 * Both instances are skipped entirely when ``getCanUseSortable()``
 * returns false — same fast-path the renderer used before extraction.
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

    // Drag-resolution context shared by both useSortable instances.
    // Captured in onDragStart and read by onDrop because useSortable's
    // params carry the drop target but not the original ``data-id``
    // of the source — we need both to dispatch the resequence RPC.
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
            // Clear any pre-existing selection so the drag affects only
            // the dragged card. Multi-select drag was historically a
            // sharp edge — records would seem to follow the drag but
            // then drop in unexpected places — so we always reduce to
            // the single dragged card.
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
