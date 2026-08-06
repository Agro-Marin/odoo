// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_renderer */

import { Component, onPatched, onWillDestroy, useRef, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { SearchModelEvent } from "@web/core/events";
import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { MOVABLE_RECORD_TYPES } from "@web/model/relational_model/dynamic_group_list";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";
import { ActionHelper } from "@web/views/action_helper";
import { useGroupManagement } from "@web/views/multi_record_group";
import { useRecordSelection } from "@web/views/multi_record_selection";
import { useBounceButton } from "@web/views/view_hook";
import { isNull } from "@web/views/view_utils";
import { Widget } from "@web/views/widgets/widget";

import { ColumnProgress } from "./column_progress.js";
import { KanbanColumnExamplesDialog } from "./kanban_column_examples_dialog.js";
import { KanbanColumnQuickCreate } from "./kanban_column_quick_create.js";
import { KanbanHeader } from "./kanban_header.js";
import { useKanbanKeyboardNavigation } from "./kanban_keyboard_nav.js";
import { KanbanRecord } from "./kanban_record.js";
import { KanbanRecordQuickCreate } from "./kanban_record_quick_create.js";
import { useKanbanSortable } from "./kanban_sortable_hook.js";

const DRAGGABLE_GROUP_TYPES = ["many2one"];

function validateColumnQuickCreateExamples(data) {
    const { allowedGroupBys = [], examples = [], foldField = "" } = data;
    if (!allowedGroupBys.length) {
        throw new Error("The example data must contain an array of allowed groupbys");
    }
    if (!examples.length) {
        throw new Error("The example data must contain an array of examples");
    }
    const someHasFoldedColumns = examples.some(
        ({ foldedColumns = [] }) => foldedColumns.length,
    );
    if (!foldField && someHasFoldedColumns) {
        throw new Error(
            "The example data must contain a fold field if there are folded columns",
        );
    }
}

export class KanbanRenderer extends Component {
    static template = "web.KanbanRenderer";
    static components = {
        Dropdown,
        DropdownItem,
        ColumnProgress,
        KanbanColumnQuickCreate,
        KanbanHeader,
        KanbanRecord,
        KanbanRecordQuickCreate,
        Widget,
        ActionHelper,
    };
    static props = [
        "archInfo",
        "Compiler",
        "list",
        "deleteRecord",
        "openRecord",
        "readonly?",
        "forceGlobalClick?",
        "noContentHelp?",
        "scrollTop?",
        "canQuickCreate?",
        "quickCreateState?",
        "progressBarState?",
        "addLabel?",
        "onAdd?",
    ];

    static defaultProps = {
        scrollTop: () => {},
    };

    /** @type {any[]} */
    dialogClose;
    /**
     * @type {{ selectionAvailable: boolean; processedIds: string[]; columnQuickCreateIsFolded: boolean }}
     */
    state;
    /** @type {any} */
    dialog;
    /** @type {any} */
    exampleData;
    /** @type {ReturnType<typeof useRecordSelection>} */
    sel;
    /** @type {ReturnType<typeof useGroupManagement>} */
    groupOps;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;
    /** @type {any} */
    lastOpenedGroupId;

    setup() {
        useRenderCounter("kanban.KanbanRenderer");
        this.quickCreateState =
            this.props.quickCreateState || useState({ groupId: false });
        this.dialogClose = [];
        this._onValidateQuickCreate = (...args) => this.props.list.createGroup(...args);
        this.state = useState({
            selectionAvailable: false,
            processedIds: [],
            columnQuickCreateIsFolded:
                !this.props.list.isGrouped || this.props.list.groups.length > 0,
        });
        this.dialog = useService("dialog");
        this.exampleData = registry
            .category(/** @type {any} */ ("kanban_examples"))
            .get(this.props.archInfo.examples, null);
        if (this.exampleData) {
            validateColumnQuickCreateExamples(this.exampleData);
        }
        this.rootRef = useRef("root");

        this.sel = useRecordSelection({
            getRecords: () => this.props.list.records,
            // Through the prototype so subclass overrides keep catching the
            // range call (e.g. documents' rendered-order range).
            rangeToggle: (record) => this.toggleRangeSelection(record),
            onSelectionModifier: (available) => {
                this.state.selectionAvailable = available;
            },
        });

        this.groupOps = useGroupManagement({
            getList: () => this.props.list,
            getArchInfo: () => this.props.archInfo,
            onGroupDeleted: () => {
                if (!this.props.list.groups.length) {
                    this.state.columnQuickCreateIsFolded = false;
                }
            },
        });

        useKanbanSortable({
            rootRef: this.rootRef,
            getCanUseSortable: () => this.canUseSortable,
            getCanResequenceRecords: () => this.canResequenceRecords,
            getCanResequenceGroups: () => this.canResequenceGroups,
            getCanMoveRecords: () => this.canMoveRecords,
            getIsGrouped: () => this.props.list.isGrouped,
            getSelection: () => this.props.list.selection,
            onSortStart: (params) => this.sortStart(params),
            onSortStop: (params) => this.sortStop(params),
            onSortRecordGroupEnter: (params) => this.sortRecordGroupEnter(params),
            onSortRecordGroupLeave: (params) => this.sortRecordGroupLeave(params),
            onSortRecordDrop: (dataRecordId, dataGroupId, params) =>
                this.sortRecordDrop(dataRecordId, dataGroupId, params),
            onSortGroupDrop: (dataGroupId, params) =>
                this.sortGroupDrop(dataGroupId, params),
        });

        useBounceButton(this.rootRef, (clickedEl) => {
            if (
                this.props.list.isGrouped
                    ? !this.props.list.recordCount
                    : !this.props.list.count || this.props.list.model.useSampleModel
            ) {
                return clickedEl.matches(
                    [
                        ".o_kanban_renderer",
                        ".o_kanban_group",
                        ".o_kanban_header",
                        ".o_column_quick_create",
                        ".o_view_nocontent_smiling_face",
                    ].join(", "),
                );
            }
            return false;
        });
        onWillDestroy(() => {
            this.dialogClose.forEach((close) => close());
        });

        if (this.env.searchModel) {
            useBus(this.env.searchModel, SearchModelEvent.FOCUS_VIEW, () => {
                const { model } = this.props.list;
                if (model.useSampleModel || !model.hasData()) {
                    return;
                }
                const firstCard = this.rootRef.el?.querySelector(".o_kanban_record");
                if (firstCard) {
                    firstCard.focus();
                }
            });
        }

        useKanbanKeyboardNavigation({
            rootRef: this.rootRef,
            getCanOpenRecords: () => this.props.archInfo.canOpenRecords,
            getQuickCreateActive: () => Boolean(this.quickCreateState.groupId),
            onSpace: (target, isRange) => this.onSpaceKeyPress(target, isRange),
            onArrowNav: (area, direction) =>
                this.focusNextCard(area, direction) ?? false,
            searchModel: this.env.searchModel,
        });

        onPatched(() => {
            if (this.lastOpenedGroupId) {
                const groups = this.getGroupsOrRecords();
                const lastOpenedGroupIndex = groups.findIndex(
                    (g) => g.group.id === this.lastOpenedGroupId,
                );
                let groupIdToFocus = this.lastOpenedGroupId;
                if (
                    lastOpenedGroupIndex >= 0 &&
                    lastOpenedGroupIndex < groups.length - 1 &&
                    groups[lastOpenedGroupIndex + 1].group.isFolded
                ) {
                    groupIdToFocus = groups[lastOpenedGroupIndex + 1].group.id;
                }
                const groupEl = /** @type {HTMLElement} */ (
                    this.rootRef.el?.querySelector(
                        `.o_kanban_group[data-id="${groupIdToFocus}"]`,
                    )
                );
                if (!groupEl) {
                    delete this.lastOpenedGroupId;
                    return;
                }
                const rect = groupEl.getBoundingClientRect();
                if (rect.x + rect.width > window.innerWidth) {
                    groupEl.scrollIntoView({
                        behavior: "smooth",
                        inline: "end",
                    });
                }
                delete this.lastOpenedGroupId;
            }
        });
    }

    get canUseSortable() {
        return !this.env.isSmall;
    }

    get canMoveRecords() {
        if (!this.canResequenceRecords) {
            return false;
        }
        const groupByField = this.props.list.groupByField;
        if (!groupByField) {
            return true;
        }
        const fieldNodes = Object.values(this.props.archInfo.fieldNodes).filter(
            (fieldNode) => fieldNode.name === groupByField.name,
        );
        let isReadonly = this.props.list.fields[groupByField.name].readonly;
        if (!isReadonly && fieldNodes.length) {
            isReadonly = fieldNodes.every((fieldNode) => {
                if (!fieldNode.readonly) {
                    return false;
                }
                try {
                    return evaluateExpr(
                        fieldNode.readonly,
                        this.props.list.evalContext,
                    );
                } catch {
                    return false;
                }
            });
        }
        return !isReadonly && this.isMovableField(groupByField);
    }

    get canResequenceGroups() {
        if (!this.props.list.isGrouped) {
            return false;
        }
        const { type } = this.props.list.groupByField;
        const { groupsDraggable } = this.props.archInfo;
        return groupsDraggable && DRAGGABLE_GROUP_TYPES.includes(type);
    }

    get canResequenceRecords() {
        const { isGrouped, orderBy } = this.props.list;
        const { handleField, recordsDraggable } = this.props.archInfo;
        return Boolean(
            recordsDraggable &&
            (isGrouped ||
                (handleField && (!orderBy[0] || orderBy[0].name === handleField))),
        );
    }

    get canShowExamples() {
        const { allowedGroupBys = [], examples = [] } = this.exampleData || {};
        const hasExamples = Boolean(examples.length);
        return (
            hasExamples && allowedGroupBys.includes(this.props.list.groupByField.name)
        );
    }

    get showNoContentHelper() {
        const { model, isGrouped, groupByField, groups } = this.props.list;
        if (model.useSampleModel) {
            return true;
        }
        if (isGrouped) {
            if (this.quickCreateState.groupId) {
                return false;
            }
            if (this.canCreateGroup() && !this.state.columnQuickCreateIsFolded) {
                return false;
            }
            if (!groups.length) {
                return groupByField.type !== "many2one";
            }
        }
        return !model.hasData();
    }

    getSelection() {
        return this.props.list.selection || [];
    }

    /**
     * @returns {any[]}
     */
    getGroupsOrRecords() {
        const { list } = this.props;
        if (list.isGrouped) {
            return [...list.groups]
                .sort((a, b) =>
                    a.value && !b.value ? 1 : !a.value && b.value ? -1 : 0,
                )
                .map((group, i) => ({
                    group,
                    key: isNull(group.value) ? `group_key_${i}` : String(group.value),
                }));
        } else {
            return list.records.map((record) => ({ record, key: record.id }));
        }
    }

    /**
     * @param {any} group
     * @param {boolean} isGroupProcessing
     * @returns {string}
     */
    getGroupClasses(group, isGroupProcessing) {
        const classes = [];
        if (!isGroupProcessing && this.canResequenceGroups && group.value) {
            classes.push("o_group_draggable");
        }
        if (!group.count) {
            classes.push("o_kanban_no_records");
        }
        if (!this.env.isSmall && group.isFolded) {
            classes.push("o_column_folded", "flex-basis-0");
        }
        if (this.props.progressBarState && !group.isFolded) {
            const progressBarInfo = this.props.progressBarState.getGroupInfo(group);
            if (progressBarInfo.activeBar) {
                const progressBar = progressBarInfo.bars.find(
                    (b) => b.value === progressBarInfo.activeBar,
                );
                if (progressBar) {
                    classes.push(
                        "o_kanban_group_show",
                        `o_kanban_group_show_${progressBar.color}`,
                    );
                }
            }
        }
        return classes.join(" ");
    }

    getGroupUnloadedCount(group) {
        const records = group.list.records.filter((r) => !r.isInQuickCreation);
        const count = this.props.progressBarState?.getGroupCount(group) ?? group.count;
        return count - records.length;
    }

    /**
     * @param {string} id
     * @returns {boolean}
     */
    isProcessing(id) {
        return this.state.processedIds.includes(id);
    }

    isMovableField(field) {
        return MOVABLE_RECORD_TYPES.includes(field.type);
    }

    canCreateGroup() {
        return this.groupOps.canCreateGroup();
    }

    async archiveRecord(record, active) {
        const reload = () => this.props.list.model.load();
        if (active) {
            this.dialog.add(ConfirmationDialog, {
                body: _t("Are you sure that you want to archive this record?"),
                confirmLabel: _t("Archive"),
                confirm: () => record.archive(reload),
                cancel: () => {},
            });
        } else {
            return record.unarchive(reload);
        }
    }

    async validateQuickCreate(recordId, mode, group) {
        const record = await group.addExistingRecord(recordId, true);
        if (mode === "edit") {
            await this.props.openRecord(record);
        } else {
            this.props.progressBarState?.updateCounts(group);
        }
        this.quickCreateState.groupId = mode === "add" ? group.id : false;
    }

    cancelQuickCreate() {
        this.quickCreateState.groupId = false;
    }

    async deleteGroup(group) {
        await this.groupOps.deleteGroup(group);
    }

    toggleGroup(group) {
        return this.groupOps.toggleGroup(group);
    }

    loadMore(group) {
        return group.list.load({
            limit: group.list.records.length + group.model.initialLimit,
        });
    }

    /**
     * @param {string} id
     * @param {boolean} isProcessing
     */
    toggleProcessing(id, isProcessing) {
        if (isProcessing) {
            this.state.processedIds = [...this.state.processedIds, id];
        } else {
            this.state.processedIds = this.state.processedIds.filter(
                (processedId) => processedId !== id,
            );
        }
    }

    /**
     * The range anchor, owned by the shared selection hook. Kept as a
     * renderer property because subclasses (e.g. documents) read it in their
     * own `toggleRangeSelection` overrides.
     */
    get lastCheckedRecord() {
        return this.sel.lastCheckedRecord;
    }

    set lastCheckedRecord(record) {
        this.sel.lastCheckedRecord = record;
    }

    toggleSelection(record, isRange = false) {
        this.sel.toggleSelection(record, isRange);
    }

    toggleRangeSelection(record) {
        this.sel.toggleRangeSelection(record);
    }

    async onGroupClick(group, ev) {
        if (!this.env.isSmall && group.isFolded) {
            this.lastOpenedGroupId = group.id;
            await group.toggle();
            this.props.scrollTop();
        }
    }

    /**
     * @param {string} dataGroupId
     * @param {Object} params
     * @param {HTMLElement} params.element
     * @param {HTMLElement} [params.group]
     * @param {HTMLElement} [params.next]
     * @param {HTMLElement} [params.parent]
     * @param {HTMLElement} [params.previous]
     */
    async sortGroupDrop(dataGroupId, { previous }) {
        this.toggleProcessing(dataGroupId, true);
        const refId = previous ? previous.dataset.id : null;
        try {
            await this.props.list.resequence(dataGroupId, refId);
        } finally {
            this.toggleProcessing(dataGroupId, false);
        }
    }

    onSpaceKeyPress(target, isRange) {
        if (target.classList.contains("o_kanban_record")) {
            const record = this.props.list.records.find(
                (e) => e.id === target.dataset.id,
            );
            this.toggleSelection(record, isRange);
        }
    }

    showExamples() {
        this.dialog.add(KanbanColumnExamplesDialog, {
            examples: this.exampleData.examples,
            applyExamplesText:
                this.exampleData.applyExamplesText || _t("Use This For My Kanban"),
            applyExamples: (index) => {
                const { examples, foldField } = this.exampleData;
                const { columns, foldedColumns = [] } = examples[index];
                for (const groupName of columns) {
                    this.props.list.createGroup(groupName);
                }
                for (const groupName of foldedColumns) {
                    this.props.list.createGroup(groupName, foldField);
                }
            },
        });
    }

    /**
     * @param {string} dataRecordId
     * @param {string | undefined} dataGroupId
     * @param {Object} params
     * @param {HTMLElement} params.element
     * @param {HTMLElement} [params.group]
     * @param {HTMLElement} [params.next]
     * @param {HTMLElement} [params.parent]
     * @param {HTMLElement} [params.previous]
     */
    async sortRecordDrop(
        dataRecordId,
        dataGroupId,
        { element, parent, previous: _previous },
    ) {
        let previous = /** @type {HTMLElement | null} */ (_previous);
        if (
            !this.props.list.isGrouped ||
            parent?.classList.contains("o_kanban_hover") ||
            parent?.dataset.id === element.parentElement?.dataset.id
        ) {
            if (!this.props.list.records.find((r) => r.id === dataRecordId)) {
                return;
            }
            this.toggleProcessing(dataRecordId, true);

            parent?.classList.remove("o_kanban_hover");
            while (previous && !previous.dataset.id) {
                previous = /** @type {HTMLElement | null} */ (
                    previous.previousElementSibling
                );
            }
            const refId = previous ? previous.dataset.id : null;
            const targetGroupId = parent?.dataset.id;
            const isGroupMove =
                this.props.list.isGrouped &&
                !!targetGroupId &&
                targetGroupId !== dataGroupId;
            if (isGroupMove) {
                this.props.progressBarState?.registerRecordMove(
                    dataRecordId,
                    dataGroupId,
                    targetGroupId,
                );
            }
            try {
                await this.props.list.moveRecord(
                    dataRecordId,
                    dataGroupId,
                    refId,
                    targetGroupId,
                );
            } finally {
                this.toggleProcessing(dataRecordId, false);
                if (isGroupMove) {
                    this.props.progressBarState?.cancelRecordMove(dataRecordId);
                }
            }
        }
    }

    /**
     * @param {Object} params
     * @param {HTMLElement} params.group
     */
    sortRecordGroupEnter({ group }) {
        group.classList.add("o_kanban_hover");
    }

    /**
     * @param {Object} params
     * @param {HTMLElement} params.group
     */
    sortRecordGroupLeave({ group }) {
        group.classList.remove("o_kanban_hover");
    }

    /**
     * @param {Object} params
     * @param {HTMLElement} params.element
     * @param {HTMLElement} [params.group]
     */
    sortStart({ element }) {
        element.classList.add("shadow");
    }

    /**
     * @param {Object} params
     * @param {HTMLElement} params.element
     * @param {HTMLElement} [params.group]
     */
    sortStop({ element, group }) {
        element.classList.remove("shadow");
        if (group) {
            group.classList.remove("o_kanban_hover");
        }
    }

    /**
     * @param {HTMLElement} area
     * @param {"down"|"up"|"right"|"left"} direction
     * @returns {true | undefined}
     */
    focusNextCard(area, direction) {
        const { isGrouped } = this.props.list;
        const closestCard = document.activeElement?.closest(".o_kanban_record");
        if (!closestCard) {
            return;
        }
        const groups = isGrouped
            ? [...area.querySelectorAll(".o_kanban_group")]
            : [area];
        const cards = [...groups]
            .map((group) => [
                ...group.querySelectorAll(
                    ".o_kanban_record:not(.o_kanban_ghost):not(.o-kanban-button-new)",
                ),
            ])
            .filter((group) => group.length);

        let iGroup;
        let iCard = -1;
        for (iGroup = 0; iGroup < cards.length; iGroup++) {
            const i = cards[iGroup].indexOf(/** @type {HTMLElement} */ (closestCard));
            if (i !== -1) {
                iCard = i;
                break;
            }
        }
        if (iCard === -1) {
            return;
        }
        let nextCard;
        switch (direction) {
            case "down":
                nextCard = iCard < cards[iGroup].length - 1 && cards[iGroup][iCard + 1];
                break;
            case "up":
                nextCard = iCard > 0 && cards[iGroup][iCard - 1];
                break;
            case "right":
                if (isGrouped) {
                    nextCard = iGroup < cards.length - 1 && cards[iGroup + 1][0];
                } else {
                    nextCard = iCard < cards[0].length - 1 && cards[0][iCard + 1];
                }
                break;
            case "left":
                if (isGrouped) {
                    nextCard = iGroup > 0 && cards[iGroup - 1][0];
                } else {
                    nextCard = iCard > 0 && cards[0][iCard - 1];
                }
                break;
        }

        if (nextCard && nextCard instanceof HTMLElement) {
            nextCard.focus();
            return true;
        }
    }
}
