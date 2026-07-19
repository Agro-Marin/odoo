// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_renderer - Table rendering, inline editing, column resize, and drag-and-drop for list view */

import {
    Component,
    onMounted,
    onPatched,
    onWillDestroy,
    onWillPatch,
    onWillRender,
    status,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { Pager } from "@web/components/pager/pager";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { AppEvent } from "@web/core/events";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { useSortable } from "@web/core/utils/dnd/sortable_owl";
import { useBus, useService } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { Field } from "@web/fields/field";
import { getTooltipInfo } from "@web/fields/field_tooltip";
import { MOVABLE_RECORD_TYPES } from "@web/model/relational_model/dynamic_group_list";
import { ActionHelper } from "@web/views/action_helper";
import { ViewButton } from "@web/views/view_button/view_button";
import { GroupConfigMenu } from "@web/views/view_components/group_config_menu";
import { useBounceButton } from "@web/views/view_hook";
import { Widget } from "@web/views/widgets/widget";

import { useMagicColumnWidths } from "./column_width_hook.js";
import { useListAggregates } from "./list_aggregates.js";
import { ListAggregatesRow } from "./list_aggregates_row.js";
import {
    getPropertyFieldColumns as getPropertyFieldColumnsUtil,
    processAllColumns,
} from "./list_column_utils.js";
import { ListGridState } from "./list_grid_state.js";
import { listGroupRenderingMixin } from "./list_group_rendering.js";
import {
    containsActiveElement,
    useListKeyboardNavigation,
} from "./list_keyboard_nav.js";
import { useListOptionalFields } from "./list_optional_fields.js";
import { getRowComponentClass } from "./list_record_row.js";
import { useListSelection } from "./list_selection.js";
import { listSortingMixin } from "./list_sorting.js";
import { listStylingMixin } from "./list_styling.js";
import { useListVirtualization } from "./list_virtualization.js";

/**
 * @typedef {import('@web/model/relational_model/dynamic_list').DynamicList} DynamicList
 * @typedef {import('@web/model/relational_model/group').Group} Group
 * @typedef {import('@web/model/relational_model/record').RelationalRecord} RelationalRecord
 * @typedef {import('@web/model/relational_model/relational_model').RelationalModel} RelationalModel
 * @typedef {import('@web/model/relational_model/static_list').StaticList} StaticList
 * @typedef {import("../view").ViewProps} ViewProps
 *
 * @typedef {import("./list_column_utils").Column} Column
 *
 * @typedef {"up" | "down" | "left" | "right"} Direction
 *
 * @typedef {ViewProps & {
 *  list: DynamicList | StaticList;
 *  archInfo?: any;
 *  editable?: any;
 *  cycleOnTab?: boolean;
 *  allowSelectors?: boolean;
 *  [key: string]: any;
 * }} ListRendererProps
 */

/** @extends Component */
export class ListRenderer extends Component {
    static template = "web.ListRenderer";
    static rowsTemplate = "web.ListRenderer.Rows";
    static createControlsTemplate = "web.ListRenderer.CreateControls";
    static recordRowTemplate = "web.ListRenderer.RecordRow";
    static groupRowTemplate = "web.ListRenderer.GroupRow";
    static useMagicColumnWidths = true;
    static LONG_TOUCH_THRESHOLD = 400;
    /** Minimum flat row count to activate row virtualization. Set Infinity to disable. */
    static VIRTUALIZATION_THRESHOLD = 100;
    static components = {
        DropdownItem,
        Field,
        ViewButton,
        CheckBox,
        Dropdown,
        Pager,
        Widget,
        ActionHelper,
        GroupConfigMenu,
        ListAggregatesRow,
    };
    static defaultProps = { allowSelectors: false, cycleOnTab: true };

    /**
     * Memoized tooltip info per column id (class field: definitely assigned,
     * so tsc doesn't widen it to ``| undefined``). See ``makeTooltip``.
     * @type {Record<string, string>}
     */
    tooltipInfoByColumn = {};

    static props = [
        "activeActions?",
        "list",
        "archInfo",
        "openRecord",
        "onAdd?",
        "cycleOnTab?",
        "allowSelectors?",
        "editable?",
        "onOpenFormView?",
        "hasOpenFormViewButton?",
        "noContentHelp?",
        "nestedKeyOptionalFieldsData?",
        "optionalActiveFields?",
        "readonly?",
    ];

    /** @type {any} */
    uiService;
    /** @type {any} */
    notificationService;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    tableRef;
    /** @type {any} */
    sel;
    /** @type {any} */
    nav;
    /** @type {any[]} */
    columns;
    /** @type {any[]} */
    allColumns;
    /** @type {any} */
    editedRecord;
    /** @type {any} */
    gridState;
    /** @type {any} */
    virt;
    /** @type {any} */
    agg;
    /** @type {any} */
    columnWidths;
    /** @type {any} */
    state;
    /** @type {any} */
    activeElement;
    /** @type {any[]} */
    dialogClose;
    /** @type {Set<string> | undefined} record ids rendered since the last full render (row cache invalidation) */
    _renderedRowIds;
    /** @type {any[] | undefined} previous identity-stable columns array */
    _stableColumns;
    /** @type {any} stable fallback for the activeActions getter */
    _defaultActiveActions;
    /** @type {any} identity-stable self reference (see setup) */
    _rendererInstance;
    /** @type {() => void} identity-stable bound ``displaySaveNotification`` (see setup) */
    _displaySaveNotification;

    setup() {
        useRenderCounter("list.ListRenderer");
        // Stable reference: template expressions run against a per-render
        // sub-context, so ``this`` isn't identity-stable across renders —
        // row skipping requires the ``renderer`` prop to stay stable.
        this._rendererInstance = this;
        // Bind once so the new-x2many-row ViewButton's ``onClick`` prop keeps a
        // stable identity across renders — an inline ``.bind(this)`` in the
        // template minted a fresh function every render, defeating the child's
        // props-stability skip (and the row-skipping contract this renderer
        // maintains everywhere else).
        this._displaySaveNotification = this.displaySaveNotification.bind(this);
        this.actionService = useService("action");
        this.uiService = useService("ui");
        this.notificationService = useService("notification");
        this.orm = useService("orm");
        const key = this.createViewKey();
        this.keyOptionalFields = `optional_fields,${key}`;
        this.keyDebugOpenView = `debug_open_view,${key}`;
        this.cellClassByColumn = {};
        this.tooltipInfoDebug = this.isDebugMode;
        this.groupByButtons = this.props.archInfo.groupBy.buttons;
        useExternalListener(
            document,
            "click",
            /** @type {EventListener} */ (this.onGlobalClick.bind(this)),
        );
        this.tableRef = useRef("table");

        this.sel = useListSelection({
            getProps: () => this.props,
            getAllowSelectors: () => this.props.allowSelectors,
            toggleRecordSelection: (record) => this.toggleRecordSelection(record),
            longTouchThreshold: /** @type {any} */ (this.constructor)
                .LONG_TOUCH_THRESHOLD,
            getEnv: () => this.env,
        });

        /**
         * If the pointer is a few pixels off the resize handle, a click can
         * fire on the column title and reorder it right after a resize — bad
         * UX we prevent via `resizing`/`preventReorder`, set in
         * onClickSortColumn, onColumnTitleMouseUp, and onStartResize.
         */
        this.preventReorder = false;

        this.controls = this.props.archInfo.controls.length
            ? this.props.archInfo.controls
            : [{ type: "create", string: _t("Add a line") }];
        this.deleteControl =
            this.controls.find((control) => control.type === "delete") || {};

        this.nav = useListKeyboardNavigation(/** @type {any} */ (this.tableRef), {
            getColumns: () => this.columns,
            getEditedRecord: () => this.editedRecord,
            getProps: () => this.props,
            getEnv: () => this.env,
            getGridState: () => this.gridState,
            onToggleGroup: (group) => this.toggleGroup(group),
            onToggleRecordSelection: (record) => this.toggleRecordSelection(record),
            onAdd: (params) => this.add(params),
            onOpenRecord: (record) => this.props.openRecord(record),
            onDeleteRecord: (record) => this.onDeleteRecord(record),
            onEditNextRecord: (record, group) => this.editNextRecord(record, group),
            // Route arrow-key cell resolution back through the renderer's
            // (overridable) findFocusFutureCell so subclass overrides
            // (documents, account_accountant attachment preview, …) participate
            // in every arrow move again — the hook's internal helpers alone are
            // a closed call the renderer twin can't intercept.
            findFocusFutureCell: (cell, cellIsInGroupRow, direction) =>
                this.findFocusFutureCell(cell, cellIsInGroupRow, direction),
            isInlineEditable: (record) => this.isInlineEditable(record),
            isCellReadonly: (column, record) => this.isCellReadonly(column, record),
            expandCheckboxes: (record, direction) =>
                this.sel.expandCheckboxes(
                    record,
                    /** @type {"up" | "down"} */ (direction),
                ),
            getCanCreate: () => this.canCreate,
            getDisplayRowCreates: () => this.displayRowCreates,
            getControls: () => this.controls,
            getSel: () => this.sel,
            getVirtualization: () => this.virt,
        });

        this.activeRowId = null;
        onMounted(async () => {
            // Due to the way elements are mounted in the DOM by Owl (bottom-to-top),
            // we need to wait the next micro task tick to set the activeElement.
            await Promise.resolve();
            this.activeElement = this.uiService.activeElement;
        });
        onWillPatch(() => {
            const activeRow = /** @type {HTMLElement | null} */ (
                document.activeElement?.closest(".o_data_row.o_selected_row")
            );
            this.activeRowId = activeRow ? activeRow.dataset.id : null;
        });
        this.opt = useListOptionalFields(
            this.keyOptionalFields,
            this.keyDebugOpenView,
            {
                getAllColumns: () => this.allColumns,
                getOptionalActiveFields: () => this.optionalActiveFields,
                onSave: () => this.saveOptionalActiveFields(),
            },
        );
        // The prop is OWNED by the controller (reactive useState there) and
        // written in place by this renderer (computeOptionalActiveFields,
        // toggle handlers) — that shared object is what keeps the
        // controller's getExportableFields in sync. useState re-wraps it on
        // this component so ListAggregatesRow can subscribe to
        // property-level mutations (optional column toggle). The fallback
        // covers embedded x2many usage, where the prop is not passed.
        this.optionalActiveFields = useState(this.props.optionalActiveFields || {});
        /** @type {Column[]} */
        this.allColumns = [];
        /** @type {Column[]} */
        this.columns = [];
        this.editedRecord = null;
        this.agg = useListAggregates({
            getColumns: () => this.columns,
            getFields: () => this.fields,
            getProps: () => this.props,
            getOptionalActiveFields: () => this.optionalActiveFields,
        });
        // User-Timing instrumentation is dev-only — in production these
        // marks would run every render and accumulate unbounded (nothing ever clears them).
        const mark = odoo.debug ? (name) => performance.mark(name) : () => {};
        const measure = odoo.debug
            ? (name, start) => performance.measure(name, start)
            : () => {};
        onWillRender(() => {
            this.editedRecord = this.props.list.editedRecord;
            this._readonlyCache = new Map();
            this._renderedRowIds = new Set();

            mark("list:processAllColumns:start");
            this.allColumns = /** @type {Column[]} */ (
                this.processAllColumns(this.props.archInfo.columns, this.props.list)
            );
            measure("list:processAllColumns", "list:processAllColumns:start");

            Object.assign(
                this.optionalActiveFields,
                this.computeOptionalActiveFields(),
            );
            // `this.opt` caches its localStorage-backed state; no per-render
            // refresh needed (toggle handlers keep it up to date).
            this.debugOpenView = this.opt.debugOpenView;

            mark("list:getActiveColumns:start");
            // Keep the columns array identity-stable when unchanged: it's
            // passed to each ListRecordRow as a prop, and referential
            // stability is what lets OWL skip unchanged rows on re-render.
            this.columns = this._toStableColumns(this.getActiveColumns());
            measure("list:getActiveColumns", "list:getActiveColumns:start");

            this.withHandleColumn = this.columns.some((col) => col.widget === "handle");

            this.gridState.update({
                list: this.props.list,
                columns: this.columns,
                hasSelectors: this.hasSelectors,
                hasOpenFormViewColumn: this.hasOpenFormViewColumn,
                hasActionsColumn: this.hasActionsColumn,
                showAddLine: Boolean(this.props.editable && this.canCreate),
            });
            mark("list:gridState.rebuild:start");
            this.gridState.rebuild();
            measure("list:gridState.rebuild", "list:gridState.rebuild:start");

            mark("list:virt.refresh:start");
            this.virt.refresh();
            measure("list:virt.refresh", "list:virt.refresh:start");
        });
        this.state = useState({ showGroupInput: false });
        let dataRowId;
        let dataGroupId;
        this.rootRef = useRef("root");
        this.resequencePromise = Promise.resolve();
        useSortable({
            enable: () => this.canResequenceRows,
            ref: this.rootRef,
            elements: ".o_row_draggable",
            handle: ".o_handle_cell",
            cursor: "grabbing",
            placeholderClasses: ["d-table-row"],
            onDragStart: (params) => {
                const { element } = params;
                dataRowId = element.dataset.id;
                dataGroupId = this.props.list.isGrouped && element.dataset.groupId;
                return this.sortStart(params);
            },
            onDragEnd: (params) => this.sortStop(params),
            onDrop: (params) => this.sortDrop(dataRowId, dataGroupId, params),
        });

        useBounceButton(this.rootRef, () => this.showNoContentHelper);

        let isSmall = this.uiService.isSmall;
        useBus(this.uiService.bus, AppEvent.RESIZE, () => {
            if (isSmall !== this.uiService.isSmall) {
                isSmall = this.uiService.isSmall;
                this.render();
            }
        });

        this.columnWidths = useMagicColumnWidths(this.tableRef, () => ({
            columns: this.columns,
            isEmpty:
                !this.props.list.records.length || this.props.list.model.useSampleModel,
            hasSelectors: this.hasSelectors,
            hasOpenFormViewColumn: this.hasOpenFormViewColumn,
            hasActionsColumn: this.hasActionsColumn,
        }));

        onPatched(async () => {
            // Wait one microtask so child Field components finish their own patch cycle.
            // OWL does not wait for children that trigger a self-patch.
            await Promise.resolve();
            if (status(this) === "destroyed") {
                return;
            }
            if (this.activeElement !== this.uiService.activeElement) {
                // Focus is owned by another UI part (e.g. a dialog): drop any
                // latched virtualized-focus retry, or it would survive this
                // patch and fire at a much later, unrelated one with stale
                // grid indexes — stealing focus.
                /** @type {any} */ (this.nav).clearPendingVirtFocus();
                return;
            }
            if (this.editedRecord && this.activeRowId !== this.editedRecord.id) {
                if (
                    this.nav.cellToFocus &&
                    this.nav.cellToFocus.record === this.editedRecord
                ) {
                    const column = this.nav.cellToFocus.column;
                    const forward = this.nav.cellToFocus.forward;
                    this.focusCell(column, forward);
                } else {
                    const column = this.nav.lastEditedCell?.column || this.columns[0];
                    // Hiding every (optional) column mid-edit leaves no
                    // column to focus — this.columns[0] is undefined then.
                    if (
                        column &&
                        (column.widget !== "daterange" ||
                            !this.editedRecord.data[column.name])
                    ) {
                        this.focusCell(column);
                    }
                }
            }
            this.nav.cellToFocus = null;
            this.nav.lastEditedCell = null;
            /** @type {any} */ (this.nav).resolvePendingVirtFocus();
        });
        this.isRTL = localization.direction === "rtl";

        this.gridState = new ListGridState({
            list: this.props.list,
            columns: this.columns,
            hasSelectors: this.hasSelectors,
            hasOpenFormViewColumn: this.hasOpenFormViewColumn,
            hasActionsColumn: this.hasActionsColumn,
            isRTL: this.isRTL,
            showAddLine: Boolean(this.props.editable && this.canCreate),
            isCellReadonly: (col, rec) => this.isCellReadonly(col, rec),
        });

        this.virt = useListVirtualization({
            rootRef: this.rootRef,
            getGridState: () => this.gridState,
            getNbCols: () => this.nbCols,
            canResequence: () => this.canResequenceRows,
            getEditedRecord: () => this.editedRecord,
            threshold: /** @type {any} */ (this.constructor).VIRTUALIZATION_THRESHOLD,
        });

        this.dialogClose = [];
        onWillDestroy(() => {
            this.dialogClose.forEach((close) => close());
        });
    }

    displaySaveNotification() {
        this.notificationService.add(_t("Please save your changes first"), {
            type: "danger",
        });
    }

    /**
     * Overridable seam around the shared column pre-processing util.
     * Sub-renderers remap column attributes before the shared processing
     * runs — e.g. account's invoice-line renderer resolves
     * optional="conditional" to "show"/"hide" from the move type. Keep
     * calling this method (not the util directly) from render paths so
     * those overrides stay effective.
     *
     * @param {Column[]} allColumns
     * @param {DynamicList | StaticList} list
     * @returns {Column[]}
     */
    processAllColumns(allColumns, list) {
        return processAllColumns(allColumns, list);
    }

    getActiveColumns() {
        return this.allColumns.filter((col) => {
            if (col.optional && !this.optionalActiveFields[col.name]) {
                return false;
            }
            if (this.evalColumnInvisible(col.column_invisible)) {
                return false;
            }
            return true;
        });
    }

    get hasSelectors() {
        return this.props.allowSelectors && !this.env.isSmall;
    }

    get hasOpenFormViewColumn() {
        return this.props.hasOpenFormViewButton || this.debugOpenView;
    }

    get hasOptionalOpenFormViewColumn() {
        return (
            this.props.editable && this.env.debug && !this.props.hasOpenFormViewButton
        );
    }

    get hasActionsColumn() {
        return !!(
            this.displayOptionalFields ||
            this.activeActions.onDelete ||
            this.hasOptionalOpenFormViewColumn ||
            // spare some space to display the cog icon in group headers
            this.props.list.isGrouped
        );
    }

    add(params) {
        if (this.canCreate) {
            this.props.onAdd(params);
        }
    }

    /**
     * @param {Column} column
     * @param {DynamicList | StaticList} list
     */
    getPropertyFieldColumns(column, list) {
        return getPropertyFieldColumnsUtil(/** @type {any} */ (column), list);
    }

    /**
     * @param {RelationalRecord} record
     * @param {Column} column
     */
    getFieldProps(record, column) {
        return {
            readonly:
                this.props.readonly ||
                this.isCellReadonly(column, record) ||
                this.isRecordReadonly(record) ||
                (column.widget === "handle" && !this.canResequenceRows),
        };
    }

    get activeActions() {
        // The fallback object must be identity-stable: it is passed to each
        // ListRecordRow as a prop (referential stability drives row skipping).
        return this.props.activeActions || (this._defaultActiveActions ||= {});
    }

    /**
     * Row component class for the rows template, derived per renderer class
     * so sub-component resolution uses this renderer's ``static components``
     * (as the historical ``t-call`` did).
     */
    get rowComponent() {
        return getRowComponentClass(/** @type {any} */ (this.constructor));
    }

    /**
     * Props for one ``ListRecordRow``. Every value must be referentially
     * stable across renders for unchanged rows (what lets OWL skip them).
     * The renderer's props are spread in so template ``props.X`` expressions
     * (including subclass ones) keep resolving; the scalar keys below are
     * computed per render and double as invalidation channels for affected
     * rows.
     *
     * @param {RelationalRecord} record
     * @param {Group | undefined} group
     * @param {string | undefined} groupId
     */
    getRowProps(record, group, groupId) {
        return {
            ...this.props,
            renderer: this._rendererInstance,
            record,
            group,
            groupId,
            recordRowTemplate: /** @type {any} */ (this.constructor).recordRowTemplate,
            columns: this.columns,
            activeActions: this.activeActions,
            // Narrow invalidation channel: pass only the two booleans a row's
            // render actually depends on instead of the whole ``editedRecord``
            // object. Passing the object made EVERY visible row see a changed
            // prop whenever the edited row switched (A -> B), re-rendering all
            // of them (~O(rows × cols) cell evals per keypress cycle). With
            // ``isEdited`` only rows A and B flip; ``hasEditedRecord`` flips for
            // all rows only on the null <-> some transition, which is exactly
            // when every row's button ``tabindex`` must actually update. The
            // row template still reads ``editedRecord`` (delegated to the
            // renderer) for its concrete value on the renders that do happen.
            isEdited: this.editedRecord === record,
            hasEditedRecord: Boolean(this.editedRecord),
            canResequence: this.canResequenceRows,
            canSelectRecord: this.canSelectRecord,
            hasSelectors: this.hasSelectors,
            hasOpenFormViewColumn: this.hasOpenFormViewColumn,
            displayOptionalFields: this.displayOptionalFields,
            isX2Many: this.isX2Many,
            rowIndex: this.gridState.findRowByRecordId(String(record.id))?.globalIndex,
        };
    }

    /**
     * Reuse the previous columns array when the recomputed one is elementwise
     * identical (see comment at the ``onWillRender`` call site).
     *
     * @param {any[]} columns
     * @returns {any[]}
     */
    _toStableColumns(columns) {
        const previous = this._stableColumns;
        if (
            previous &&
            previous.length === columns.length &&
            columns.every((col, i) => col === previous[i])
        ) {
            return previous;
        }
        this._stableColumns = columns;
        return columns;
    }

    /**
     * Called by ``ListRecordRow`` at the start of each row render, to evict
     * stale ``_readonlyCache`` entries when a row re-renders without a full
     * renderer render. Skipped on the first row render after a full render,
     * since the cache was just recreated empty.
     *
     * @param {string} recordId
     */
    markRowRender(recordId) {
        if (!this._renderedRowIds) {
            return;
        }
        if (this._renderedRowIds.has(recordId)) {
            this.clearRecordCaches(recordId);
        } else {
            this._renderedRowIds.add(recordId);
        }
    }

    /**
     * Evict all ``_readonlyCache`` entries for one record. The cache is
     * two-level — ``Map<recordId, Map<columnKey, value>>`` (see
     * ``list_styling.js``) — precisely so this eviction, which runs on every
     * isolated row re-render, is O(1) instead of a scan of all keys.
     *
     * @param {string} recordId
     */
    clearRecordCaches(recordId) {
        this._readonlyCache?.delete(recordId);
    }

    get canResequenceRows() {
        if (!this.props.list.canResequence() || this.props.readonly) {
            return false;
        }
        const { groupBy, groupByField, handleField, orderBy } = this.props.list;
        if (
            groupBy?.length > 1 ||
            (groupByField && !MOVABLE_RECORD_TYPES.includes(groupByField.type))
        ) {
            return false;
        }
        return !orderBy.length || (orderBy.length && orderBy[0].name === handleField);
    }

    get fields() {
        return this.props.list.fields;
    }

    get nbCols() {
        let nbCols = this.columns.length;
        if (this.hasSelectors) {
            nbCols++;
        }
        if (this.hasActionsColumn) {
            nbCols++;
        }
        if (this.hasOpenFormViewColumn) {
            nbCols++;
        }
        return nbCols;
    }

    focusCell(column, forward = true) {
        this.nav.focusCell(column, forward);
    }

    /**
     * @param {HTMLElement} el
     */
    focus(el) {
        this.nav.focus(el);
    }

    createViewKey() {
        let keyParts = {
            fields: this.props.list.fieldNames, // FIXME: use something else?
            model: this.props.list.resModel,
            viewMode: "list",
            viewId: this.env.config.viewId,
        };

        if (this.props.nestedKeyOptionalFieldsData) {
            keyParts = Object.assign(keyParts, {
                model: this.props.nestedKeyOptionalFieldsData.model,
                viewMode: this.props.nestedKeyOptionalFieldsData.viewMode,
                relationalField: this.props.nestedKeyOptionalFieldsData.field,
                subViewType: "list",
            });
        }

        const parts = ["model", "viewMode", "viewId", "relationalField", "subViewType"];
        const viewIdentifier = [];
        parts.forEach((partName) => {
            if (partName in keyParts) {
                viewIdentifier.push(keyParts[partName]);
            }
        });
        keyParts.fields
            .sort((left, right) => (left < right ? -1 : 1))
            .forEach((fieldName) => viewIdentifier.push(fieldName));
        return viewIdentifier.join(",");
    }

    get optionalFieldGroups() {
        const propertyGroups = {};
        const optionalFields = [];
        const optionalColumns = this.allColumns.filter(
            (col) => col.optional && !this.evalColumnInvisible(col.column_invisible),
        );
        for (const col of optionalColumns) {
            const optionalField = {
                label: col.label,
                name: col.name,
                value: this.optionalActiveFields[col.name],
            };
            if (!col.relatedPropertyField) {
                optionalFields.push(optionalField);
            } else {
                const { displayName, id } = /** @type {any} */ (
                    col.relatedPropertyField
                );
                if (propertyGroups[id]) {
                    propertyGroups[id].optionalFields.push(optionalField);
                } else {
                    propertyGroups[id] = {
                        id,
                        displayName,
                        optionalFields: [optionalField],
                    };
                }
            }
        }
        if (optionalFields.length) {
            return [{ optionalFields }, ...Object.values(propertyGroups)];
        }
        return Object.values(propertyGroups);
    }

    get hasOptionalFields() {
        return this.allColumns.some(
            (col) => col.optional && !this.evalColumnInvisible(col.column_invisible),
        );
    }

    get displayOptionalFields() {
        return this.hasOptionalFields;
    }

    get selectAll() {
        const list = this.props.list;
        const nbDisplayedRecords = list.records.length;
        if (list.isDomainSelected) {
            return true;
        } else {
            return (
                nbDisplayedRecords > 0 && list.selection.length === nbDisplayedRecords
            );
        }
    }

    /**
     * @param {RelationalRecord} _record
     */
    getColumns(_record) {
        return this.columns;
    }

    get canCreate() {
        return "link" in this.activeActions
            ? this.activeActions.link
            : this.activeActions.create;
    }

    get isX2Many() {
        return this.activeActions.type !== "view";
    }

    get getEmptyRowIds() {
        let nbEmptyRow = Math.max(0, 4 - this.props.list.records.length);
        if (nbEmptyRow > 0 && this.displayRowCreates) {
            nbEmptyRow -= 1;
        }
        return Array.from({ length: nbEmptyRow }, (_, i) => i);
    }

    get displayRowCreates() {
        return this.isX2Many && this.canCreate;
    }

    /**
     * @param {RelationalRecord} record
     */
    displayDeleteIcon(record) {
        return !evaluateBooleanExpr(this.deleteControl.invisible, record.evalContext);
    }

    computeOptionalActiveFields() {
        return this.opt.computeOptionalActiveFields();
    }

    /**
     * @param {RelationalRecord} record
     * @param {Column} column
     * @param {PointerEvent} ev
     */
    onButtonCellClicked(record, column, ev) {
        if (!(/** @type {HTMLElement} */ (ev.target).closest("button"))) {
            this.onCellClicked(record, column, ev);
        }
    }

    /**
     * @param {RelationalRecord} record
     * @param {Column} column
     * @param {PointerEvent} ev
     * @param {boolean} [newWindow]
     */
    async onCellClicked(record, column, ev, newWindow) {
        if (/** @type {any} */ (ev.target).special_click) {
            return;
        }

        const multiEdit = this.props.list.model.multiEdit;
        const hasSelection = !!this.props.list.selection.length;
        if (hasSelection && this.canSelectRecord && (!multiEdit || !record.selected)) {
            this.toggleRecordSelection(record);
        } else if (
            (multiEdit && record.selected) ||
            (this.isInlineEditable(record) && !hasSelection)
        ) {
            if (record.isInEdition && this.editedRecord === record) {
                const cell = /** @type {HTMLElement} */ (
                    this.tableRef.el
                ).querySelector(`.o_selected_row td[name='${column.name}']`);
                if (cell && containsActiveElement(cell)) {
                    this.nav.lastEditedCell = { column, record };
                    // Cell is already focused.
                    return;
                }
                this.focusCell(column);
                this.nav.cellToFocus = null;
            } else {
                const recordId = record.id;
                await this.resequencePromise;
                // row might have changed position after resequence — look up by id
                record =
                    this.props.list.records.find((r) => r.id === recordId) || record;
                await this.props.list.enterEditMode(record);
                this.nav.cellToFocus = { column, record };
                if (
                    column.type === "field" &&
                    record.fields[column.name].type === "boolean" &&
                    (!column.widget || column.widget === "boolean")
                ) {
                    if (
                        !this.isCellReadonly(column, record) &&
                        !this.evalInvisible(
                            /** @type {string} */ (column.invisible),
                            record,
                        )
                    ) {
                        await record.update({
                            [column.name]: !record.data[column.name],
                        });
                    }
                }
            }
        } else if (this.editedRecord && this.editedRecord !== record) {
            await this.props.list.leaveEditMode();
        } else if (!this.props.archInfo.noOpen) {
            this.props.openRecord(record, { newWindow });
        }
    }

    /**
     * @param {RelationalRecord} record
     * @param {PointerEvent} ev
     */
    async onRemoveCellClicked(record, ev) {
        const element = /** @type {HTMLElement} */ (
            /** @type {HTMLElement} */ (ev.target).closest(".o_list_record_remove")
        );
        if (element.dataset.clicked) {
            return;
        }
        element.dataset.clicked = "true";
        try {
            await this.onDeleteRecord(record);
        } finally {
            delete element.dataset.clicked;
        }
    }

    openMultiCurrencyPopover(ev, value, fieldName) {
        this.agg.openMultiCurrencyPopover(ev, value, fieldName);
    }

    /**
     * @param {RelationalRecord} record
     */
    async onDeleteRecord(record) {
        if (this.editedRecord && this.editedRecord !== record) {
            const left = await this.props.list.leaveEditMode();
            if (!left) {
                return;
            }
        }
        if (this.activeActions.onDelete) {
            return this.activeActions.onDelete(record);
        }
    }

    /**
     * @param {HTMLTableCellElement} cell
     * @param {boolean} cellIsInGroupRow
     * @param {Direction} direction
     */
    findFocusFutureCell(cell, cellIsInGroupRow, direction) {
        return this.nav.findFocusFutureCell(cell, cellIsInGroupRow, direction);
    }

    /**
     * @param {RelationalRecord} _record
     */
    isInlineEditable(_record) {
        // /!\ the keyboard navigation works under the hypothesis that all or
        // none records are editable.
        return !!this.props.editable;
    }

    /**
     * @param {KeyboardEvent} ev
     * @param {Group | null} group
     * @param {RelationalRecord | null} record
     */
    onCellKeydown(ev, group = null, record = null) {
        if (this.props.list.model.useSampleModel) {
            return;
        }

        const hotkey = getActiveHotkey(ev);

        if (
            /** @type {HTMLElement} */ (ev.target).tagName === "TEXTAREA" &&
            hotkey === "enter"
        ) {
            return;
        }

        const closestCell = /** @type {HTMLTableCellElement} */ (
            /** @type {HTMLElement} */ (ev.target).closest("td, th")
        );
        if (closestCell.querySelector(".o_select_menu [aria-expanded=true]")) {
            return;
        }

        if (this.nav.toggleFocusInsideCell(hotkey, closestCell)) {
            return;
        }

        const handled = this.editedRecord
            ? this.onCellKeydownEditMode(hotkey, closestCell, group, record)
            : this.onCellKeydownReadOnlyMode(hotkey, closestCell, group, record); // record is supposed to be not null here

        if (handled) {
            for (const tbody of /** @type {HTMLElement} */ (
                this.tableRef.el
            ).getElementsByTagName("tbody")) {
                tbody.classList.add("o_keyboard_navigation");
            }
            ev.preventDefault();
            ev.stopPropagation();
        }
    }

    editNextRecord(record, group) {
        const list = this.props.list;
        const topReCreate = this.props.editable === "top" && record.isNew;
        const index = list.records.indexOf(record);
        let futureRecord = list.records[index + 1];
        if (topReCreate && index === 0) {
            futureRecord = null;
        }

        if (!futureRecord && !this.canCreate) {
            futureRecord = list.records[0];
        }

        if (futureRecord) {
            // Saving below may reload/resort the record set, so re-resolve
            // the target by id afterward instead of editing a detached
            // datapoint (same pattern as onCellClicked's post-resequence lookup).
            const futureRecordId = futureRecord.id;
            list.leaveEditMode({ validate: true }).then((canProceed) => {
                if (canProceed) {
                    const target =
                        list.records.find((r) => r.id === futureRecordId) ??
                        list.records[index + 1] ??
                        list.records.at(-1);
                    if (target) {
                        list.enterEditMode(target);
                    }
                }
            });
        } else if (
            this.nav.lastIsDirty ||
            !record.canBeAbandoned ||
            this.displayRowCreates
        ) {
            this.add({ group });
        } else {
            futureRecord = list.records.at(0);
            list.enterEditMode(futureRecord);
        }
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @param {Group | null} group
     * @param {RelationalRecord | null} record
     * @returns {boolean} true if some behavior has been taken
     */
    onCellKeydownEditMode(hotkey, cell, group, record) {
        return this.nav.onCellKeydownEditMode(hotkey, cell, group, record);
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @param {Group | null} group
     * @param {RelationalRecord | null} record
     * @returns {boolean} true if some behavior has been taken
     */
    onCellKeydownReadOnlyMode(hotkey, cell, group, record) {
        return this.nav.onCellKeydownReadOnlyMode(hotkey, cell, group, record);
    }

    saveOptionalActiveFields() {
        this.opt.saveOptionalActiveFields();
    }

    get showNoContentHelper() {
        const { model } = this.props.list;
        return this.props.noContentHelp && (model.useSampleModel || !model.hasData());
    }

    get canSelectRecord() {
        return !this.editedRecord && !this.props.list.model.useSampleModel;
    }

    toggleSelection() {
        const list = this.props.list;
        if (!this.canSelectRecord) {
            return;
        }
        return list.toggleSelection();
    }

    /**
     * @param {RelationalRecord} record
     * @param {PointerEvent} [_ev]
     */
    toggleRecordSelection(record, _ev) {
        if (!this.canSelectRecord) {
            return;
        }
        const isRecordPresent = this.props.list.records.includes(
            this.sel.lastCheckedRecord,
        );
        if (this.sel.shiftKeyMode && isRecordPresent) {
            this.sel.toggleRangeSelection(record);
        } else {
            record.toggleSelection();
        }
        this.sel.lastCheckedRecord = record;
    }

    /**
     * @param {string} fieldName
     */
    async toggleOptionalField(fieldName) {
        this.opt.toggleOptionalField(fieldName, () => this.render());
    }

    /**
     * @param {string} groupId
     */
    toggleOptionalFieldGroup(groupId) {
        this.opt.toggleOptionalFieldGroup(groupId, () => this.render());
    }

    toggleDebugOpenView() {
        this.opt.toggleDebugOpenView(() => this.render());
        this.debugOpenView = this.opt.debugOpenView;
    }

    /**
     * @param {PointerEvent} ev
     */
    onGlobalClick(ev) {
        if (!(this.editedRecord || this.state.showGroupInput)) {
            return; // there's no row or group in edition
        }

        /** @type {HTMLElement} */ (this.tableRef.el)
            .querySelector("tbody")
            ?.classList.remove("o_keyboard_navigation");

        const target = /** @type {HTMLElement} */ (ev.target);
        // Close group input when the user clicks anywhere except the input itself.
        // The input now lives in ListAggregatesRow so we use CSS class instead of ref.
        if (this.state.showGroupInput && !target.closest(".o_list_group_input")) {
            this.state.showGroupInput = false;
        }
        if (
            /** @type {HTMLElement} */ (this.tableRef.el).contains(target) &&
            target.closest(".o_data_row")
        ) {
            // Clicks originating from a record row are handled by the renderer.
            return;
        }
        if (this.activeElement !== this.uiService.activeElement) {
            return;
        }
        if (target.closest(".o_datetime_picker")) {
            return;
        }
        // Legacy autocomplete
        if (target.closest(".ui-autocomplete")) {
            return;
        }
        this.props.list.leaveEditMode();
    }

    get isDebugMode() {
        return Boolean(odoo.debug);
    }

    /**
     * @param {Column} column
     */
    makeTooltip(column) {
        // Memoized per column id: tooltip info is stable for the renderer's
        // lifetime except for the debug flag (invalidates the cache) and
        // property columns, whose definitions can change at runtime.
        if (this.tooltipInfoDebug !== this.isDebugMode) {
            this.tooltipInfoDebug = this.isDebugMode;
            this.tooltipInfoByColumn = {};
        }
        if (!column.relatedPropertyField && this.tooltipInfoByColumn[column.id]) {
            return this.tooltipInfoByColumn[column.id];
        }
        const tooltipInfo = getTooltipInfo({
            viewMode: "list",
            resModel: this.props.list.resModel,
            field: this.fields[column.name],
            // ``Column`` carries a ``widget`` plus list-specific layout
            // fields not declared on ``FieldInfo``; the tooltip only reads
            // the ``FieldInfo``-shaped subset.
            fieldInfo: /** @type {any} */ (column),
        });
        this.tooltipInfoByColumn[column.id] = tooltipInfo;
        return tooltipInfo;
    }

    onColumnTitleMouseUp() {
        if (this.columnWidths.resizing) {
            this.preventReorder = true;
        }
    }

    /**
     * @param {RelationalRecord} record
     * @param {TouchEvent} ev
     */
    onRowTouchStart(record, ev) {
        this.sel.onRowTouchStart(record, ev);
    }

    /**
     * @param {RelationalRecord} _record
     */
    onRowTouchEnd(_record) {
        this.sel.onRowTouchEnd(_record);
    }

    /**
     * @param {RelationalRecord} _record
     */
    onRowTouchMove(_record) {
        this.sel.onRowTouchMove(_record);
    }

    /**
     * @param {MouseEvent} ev
     */
    ignoreEventInSelectionMode(ev) {
        this.sel.ignoreEventInSelectionMode(ev);
    }

    /**
     * @param {RelationalRecord} record
     * @param {PointerEvent} ev
     */
    onClickCapture(record, ev) {
        this.sel.onClickCapture(record, ev);
    }
}

// Apply the cohort mixins onto ``ListRenderer.prototype`` so subclasses'
// ``super.<method>(...)`` keeps resolving to the canonical implementations
// (see each mixin module for its own rationale).
//
// Descriptor copying (not ``Object.assign``) is required for two reasons:
// ``Object.assign`` would invoke each getter at install time (where
// ``this.props`` is undefined) and copy the resulting value rather than the
// getter itself; and object-literal descriptors default to
// ``enumerable: true`` while class getters are ``enumerable: false`` — OWL's
// reactivity-capture path iterates enumerable own properties and would throw
// reading a getter-only property during capture, so we force
// ``enumerable: false`` to match class-getter semantics.
function installListRendererMixin(mixin) {
    const descriptors = Object.getOwnPropertyDescriptors(mixin);
    for (const key of Object.keys(descriptors)) {
        descriptors[key].enumerable = false;
    }
    Object.defineProperties(ListRenderer.prototype, descriptors);
}
installListRendererMixin(listStylingMixin);
installListRendererMixin(listGroupRenderingMixin);
installListRendererMixin(listSortingMixin);
