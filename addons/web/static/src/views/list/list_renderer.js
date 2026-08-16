// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_renderer */

import {
    Component,
    onMounted,
    onPatched,
    onWillDestroy,
    onWillPatch,
    onWillRender,
    reactive,
    status,
    useExternalListener,
    useRef,
    useState,
} from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { Pager } from "@web/components/pager/pager";
import { useAction } from "@web/core/action_port";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { AppEvent } from "@web/core/events";
import { localization } from "@web/core/l10n/localization";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { useSortable } from "@web/core/utils/dnd/sortable_owl";
import { useBus, useService } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { Field } from "@web/fields/field";
import { getTooltipInfo } from "@web/fields/field_tooltip";
import { MOVABLE_RECORD_TYPES } from "@web/model/relational_model/dynamic_group_list";
import { ActionHelper } from "@web/views/action_helper";
import { useGroupManagement } from "@web/views/multi_record_group";
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
import { containsActiveElement } from "./list_focus.js";
import { ListGridState } from "./list_grid_state.js";
import { listGroupRenderingMixin } from "./list_group_rendering.js";
import { useListKeyboardNavigation } from "./list_keyboard_nav.js";
import { useListOptionalFields } from "./list_optional_fields.js";
import { getRowComponentClass } from "./list_record_row.js";
import { useListSelection } from "./list_selection.js";
import { listSortingMixin } from "./list_sorting.js";
import { listStylingMixin } from "./list_styling.js";
import {
    DEFAULT_THRESHOLD as DEFAULT_VIRTUALIZATION_THRESHOLD,
    useListVirtualization,
} from "./list_virtualization.js";

// Named so a profile shows which phase of `syncRenderState` a sample landed
// in. `odoo.debug` is read per call rather than captured once, so toggling
// debug mode at runtime starts and stops the marks immediately.
const perfMark = (/** @type {string} */ name) => {
    if (odoo.debug) {
        performance.mark(name);
    }
};
const perfMeasure = (/** @type {string} */ name, /** @type {string} */ start) => {
    if (odoo.debug) {
        performance.measure(name, start);
    }
};

/**
 * @typedef {import('@web/model/relational_model/dynamic_list').DynamicList} DynamicList
 * @typedef {import('@web/model/relational_model/group').Group} Group
 * @typedef {import('@web/model/relational_model/record').RelationalRecord} RelationalRecord
 * @typedef {import('@web/model/relational_model/relational_model').RelationalModel} RelationalModel
 * @typedef {import('@web/model/relational_model/static_list').StaticList} StaticList
 * @typedef {import("../view").ViewProps} ViewProps
 * @typedef {import("./list_column_utils").Column} Column
 * @typedef {"up" | "down" | "left" | "right"} Direction
 * @typedef {ViewProps & {
 *  list: DynamicList | StaticList;
 *  archInfo?: any;
 *  editable?: any;
 *  cycleOnTab?: boolean;
 *  allowSelectors?: boolean;
 *  [key: string]: any;
 * }} ListRendererProps
 *
 * The renderer's live surface, shared by every list satellite hook
 * (selection, keyboard nav, optional fields, aggregates, virtualization) in
 * place of a per-hook callback bag. Getters read renderer state at call time;
 * the `on*`/action members are bound callbacks. Hooks destructure the subset
 * they use. See where it is built in `ListRenderer.setup`.
 * @typedef {{
 *  getProps: () => ListRendererProps;
 *  getEnv: () => any;
 *  getColumns: () => Column[];
 *  getAllColumns: () => Column[];
 *  getFields: () => Record<string, object>;
 *  getGridState: () => import("./list_grid_state").ListGridState;
 *  getEditedRecord: () => any;
 *  getOptionalActiveFields: () => Record<string, boolean>;
 *  getAllowSelectors: () => boolean;
 *  getCanCreate: () => boolean;
 *  getDisplayRowCreates: () => boolean;
 *  getControls: () => any[];
 *  getSel: () => any;
 *  getVirtualization: () => import("./list_virtualization").ListVirtualization | undefined;
 *  canResequence: () => boolean;
 *  toggleRecordSelection: (record: object) => void;
 *  onToggleGroup: (group: object) => void;
 *  onAdd: (params?: object) => void;
 *  onOpenRecord: (record: object) => void;
 *  onDeleteRecord: (record: object) => void;
 *  onEditNextRecord: (record: object, group?: object) => any;
 *  onSave: () => void;
 *  findFocusFutureCell: (cell: HTMLTableCellElement, cellIsInGroupRow: boolean, direction: Direction) => HTMLElement | null;
 *  isInlineEditable: (record: object) => boolean;
 *  isCellReadonly: (column: any, record: object) => boolean;
 *  expandCheckboxes: (record: object, direction: string) => boolean;
 * }} ListGridContext
 *
 * The cross-row booleans shared by every record row, as ONE stable reactive
 * object (`this.rowFlags`, passed to rows as the `flags` prop). A row that
 * reads a flag subscribes to that key only, so a flip re-renders exactly the
 * rows whose output depends on it — unlike a per-row prop, which invalidates
 * every row. Updated in `onWillRender`; a write of an unchanged value
 * notifies nobody.
 *
 * Every flag here is read by potentially EVERY row, so none of them may
 * round-trip within a single interaction: a value that goes `a -> b -> a`
 * repaints the whole list twice for a state no frame ever shows. In
 * particular, derive nothing here from `list.editedRecord`, which is
 * transiently null while edition is handed from one row to the next — use
 * `list.isEditing`, which spans the handover. See CONVENTIONS.md gotcha 18.
 * @typedef {{
 *  isEditing: boolean;
 *  canSelectRecord: boolean;
 * }} ListRowFlags
 *
 * The callbacks a record row may call on its renderer (`this.rowApi`, passed
 * to rows as the `api` prop; built once in `setup` by `buildRowApi`, which a
 * subclass extends to expose additional members to its row template). Every
 * member routes through the renderer INSTANCE, so prototype overrides in the
 * ~40 renderer subclasses keep catching the calls. Rendering reads receive
 * the row's own reactive `record`, so what they read subscribes the calling
 * row; action callbacks resolve record/group arguments back to the
 * renderer's reactivity context first (see `resolveRowRecord`), keeping the
 * identity comparisons in the renderer and the model valid.
 * @typedef {{
 *  getRowClass: (record: RelationalRecord) => string;
 *  getColumns: (record: RelationalRecord) => Column[];
 *  evalInvisible: (invisible: string, record: RelationalRecord) => boolean;
 *  canUseFormatter: (column: any, record: RelationalRecord) => boolean;
 *  getFormattedValue: (column: any, record: RelationalRecord) => any;
 *  getCellClass: (column: any, record: RelationalRecord) => string;
 *  getCellTitle: (column: any, record: RelationalRecord, formattedValue?: string) => string | undefined;
 *  getFieldClass: (column: any) => string;
 *  getFieldProps: (record: RelationalRecord, column: any) => object;
 *  displayDeleteIcon: (record: RelationalRecord) => boolean;
 *  onCellClicked: (record: RelationalRecord, column: any, ev: PointerEvent, newWindow?: boolean) => any;
 *  onButtonCellClicked: (record: RelationalRecord, column: any, ev: PointerEvent) => any;
 *  onRemoveCellClicked: (record: RelationalRecord, ev: PointerEvent) => any;
 *  onCellKeydown: (ev: KeyboardEvent, group?: Group | null, record?: object | null) => any;
 *  toggleRecordSelection: (record: any, ev?: any) => any;
 *  onRowTouchStart: (record: RelationalRecord, ev: TouchEvent) => void;
 *  onRowTouchEnd: (record: RelationalRecord) => void;
 *  onRowTouchMove: (record: RelationalRecord) => void;
 *  onClickCapture: (record: RelationalRecord, ev: PointerEvent) => void;
 *  ignoreEventInSelectionMode: (ev: MouseEvent) => void;
 *  getGridState: () => import("./list_grid_state").ListGridState;
 *  getEditedRecord: () => any;
 *  displaySaveNotification: () => void;
 *  markRowRender: (recordId: string) => void;
 * }} ListRowApi
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
    static VIRTUALIZATION_THRESHOLD = DEFAULT_VIRTUALIZATION_THRESHOLD;
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
     * @type {Record<string, string>}
     */
    tooltipInfoByColumn = {};

    /** @type {import("./list_renderer").ListGridContext} */
    gridContext;

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
    /** @type {ReturnType<typeof useGroupManagement>} */
    groupOps;
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
    /** @type {Set<string> | undefined} */
    _renderedRowIds;
    /** @type {any[] | undefined} */
    _stableColumns;
    /** @type {any} */
    _defaultActiveActions;
    /** @type {() => void} */
    _displaySaveNotification;
    /** @type {import("./list_renderer").ListRowFlags} */
    rowFlags;
    /** @type {import("./list_renderer").ListRowApi} */
    rowApi;

    setup() {
        // Split into ordered PHASES, not by concern. The original order is
        // deliberately interleaved -- `gridState` is built near the end, after
        // the hooks that resolve it lazily -- and OWL registers lifecycle
        // hooks in call order, so regrouping these by topic would change
        // behaviour. Each phase is called synchronously from here, so every
        // hook still registers exactly where it did before.
        this.setupServices();
        this.setupSharedContexts();
        this.setupRowInteractions();
        this.setupLayoutAndFocus();
    }

    /**
     * Services, the per-view storage keys, and the table ref. Nothing here
     * reads another phase's state.
     *
     * @returns {void}
     */
    setupServices() {
        useRenderCounter("list.ListRenderer");
        this._displaySaveNotification = this.displaySaveNotification.bind(this);
        this.actionService = useAction();
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
    }

    /**
     * The two shared surfaces: `gridContext` for the satellite hooks and
     * the row context (`rowFlags` + `rowApi`) for the record rows. Built
     * before the hooks that capture them.
     *
     * @returns {void}
     */
    setupSharedContexts() {
        // The single surface the list satellite hooks read from: one typed
        // context built once, rather than a separate callback bag per hook (with
        // the keyboard-nav hook cross-wiring into selection and virtualization).
        // Every member is a lazy getter or a bound callback, so a hook built
        // before `this.sel` / `this.virt` / `this.gridState` exist still resolves
        // them at call time. Hook-specific *config* (refs, thresholds, storage
        // keys) is passed separately -- it is not part of the shared surface.
        /** @type {import("./list_renderer").ListGridContext} */
        this.gridContext = this.buildGridContext();

        // The record rows' explicit row context: one stable reactive flags
        // object and one stable api object shared by every row (see the
        // ListRowFlags / ListRowApi typedefs above). Stable identities keep
        // the rows' `t-props` diff clean; the flags reactive carries the
        // cross-row flips.
        this.rowFlags = reactive({ isEditing: false, canSelectRecord: true });
        this.rowApi = this.buildRowApi();
    }

    /**
     * The hooks that act on rows -- selection, group management, keyboard
     * navigation, optional fields, aggregates -- plus the per-render state
     * sync. `onMounted`/`onWillPatch` here record which row held focus so
     * `setupLayoutAndFocus`'s `onPatched` can put it back.
     *
     * @returns {void}
     */
    setupRowInteractions() {
        this.sel = useListSelection(this.gridContext, {
            longTouchThreshold: /** @type {any} */ (this.constructor)
                .LONG_TOUCH_THRESHOLD,
        });

        this.groupOps = useGroupManagement({
            getList: () => this.props.list,
            getArchInfo: () => this.props.archInfo,
            isReadonly: () => this.props.readonly,
            getMenuActiveActions: () => this.props.activeActions,
            getDialogClose: () => this.dialogClose,
        });

        this.controls = this.props.archInfo.controls.length
            ? this.props.archInfo.controls
            : [{ type: "create", string: _t("Add a line") }];
        this.deleteControl =
            this.controls.find((control) => control.type === "delete") || {};

        this.nav = useListKeyboardNavigation(
            /** @type {any} */ (this.tableRef),
            this.gridContext,
        );

        this.activeRowId = null;
        onMounted(async () => {
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
            this.gridContext,
        );
        this.optionalActiveFields = useState(this.props.optionalActiveFields || {});
        /** @type {Column[]} */
        this.allColumns = [];
        /** @type {Column[]} */
        this.columns = [];
        this.editedRecord = null;
        this.agg = useListAggregates(this.gridContext);
        onWillRender(() => this.syncRenderState());
    }

    /**
     * Layout and geometry (resequencing, column widths, virtualization,
     * grid state) and the `onPatched` pass that restores the caret to the
     * edited cell. `gridState` is constructed here, near the end, because
     * `gridState.update()` in `syncRenderState` supplies the rest -- passing
     * it earlier would read half-initialised getters.
     *
     * @returns {void}
     */
    setupLayoutAndFocus() {
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

        onPatched(() => this.restoreEditionFocus());
        this.isRTL = localization.direction === "rtl";

        // Everything else is (re)set by gridState.update() in onWillRender, which
        // runs before the first render — passing it here would only read
        // half-initialized getters (e.g. hasOpenFormViewColumn via debugOpenView).
        this.gridState = new ListGridState({
            list: this.props.list,
            columns: this.columns,
            isRTL: this.isRTL,
        });

        this.virt = useListVirtualization(this.gridContext, {
            rootRef: this.rootRef,
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
            this.props.editable && this.isDebugMode && !this.props.hasOpenFormViewButton
        );
    }

    get hasActionsColumn() {
        return !!(
            this.displayOptionalFields ||
            this.activeActions.onDelete ||
            this.hasOptionalOpenFormViewColumn ||
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
        return this.props.activeActions || (this._defaultActiveActions ||= {});
    }

    get rowComponent() {
        return getRowComponentClass(/** @type {any} */ (this.constructor));
    }

    /**
     * Resolves a record received from a row's action callback back to this
     * renderer's reactivity context, by id. Rows hold their own reactive over
     * the same record, so `===` against renderer-side state (`editedRecord`,
     * `list.records`) only holds after this translation. Non-record values
     * pass through untouched.
     *
     * @param {any} record
     */
    resolveRowRecord(record) {
        if (!record || typeof record !== "object") {
            return record;
        }
        return this.gridState.findRowByRecordId(String(record.id))?.record ?? record;
    }

    /**
     * Group counterpart of `resolveRowRecord`.
     *
     * @param {any} group
     */
    resolveRowGroup(group) {
        if (!group || typeof group !== "object") {
            return group;
        }
        return this.gridState.findRowByGroupId(String(group.id))?.group ?? group;
    }

    /**
     * Puts the caret back in the edited cell after a patch.
     *
     * The leading `await` is load-bearing: it lets the browser finish its own
     * focus handling for this patch before we read `document.activeElement`,
     * so the destroyed guard below is a real possibility rather than
     * defensive noise. `setupRowInteractions` recorded `activeRowId` in
     * `onWillPatch`, i.e. BEFORE the DOM moved; comparing it with the edited
     * record is how we tell "the user moved rows" from "the row re-rendered
     * underneath a caret that should stay put".
     *
     * Bails without touching focus when the active element belongs to someone
     * else (a dialog, an autocomplete) -- stealing it back would fight them.
     *
     * @returns {Promise<void>}
     */
    async restoreEditionFocus() {
        await Promise.resolve();
        if (status(this) === "destroyed") {
            return;
        }
        if (this.activeElement !== this.uiService.activeElement) {
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
    }

    /**
     * Everything the template needs derived and published, once per render.
     * Runs from `onWillRender`, so it is the last point at which a derived
     * value can still be written before the template reads it.
     *
     * Order is load-bearing: `allColumns` feeds `getActiveColumns`, which
     * feeds `gridState.update`, which `gridState.rebuild` materialises and
     * `virt.refresh` then windows. A subclass overriding this must call
     * `super.syncRenderState()` rather than reorder it.
     *
     * @returns {void}
     */
    syncRenderState() {
        this.editedRecord = this.props.list.editedRecord;
        // `list.isEditing`, not `Boolean(this.editedRecord)`: see the
        // ListRowFlags typedef. Rows with a button column subscribe to this
        // key, and deriving it from `editedRecord` made moving the edited
        // row repaint every one of them twice.
        this.rowFlags.isEditing = this.props.list.isEditing;
        this.rowFlags.canSelectRecord = this.canSelectRecord;
        this._readonlyCache = new Map();
        this._renderedRowIds = new Set();

        if (this.tooltipInfoDebug !== this.isDebugMode) {
            this.tooltipInfoDebug = this.isDebugMode;
            this.tooltipInfoByColumn = {};
        }

        perfMark("list:processAllColumns:start");
        this.allColumns = /** @type {Column[]} */ (
            this.processAllColumns(this.props.archInfo.columns, this.props.list)
        );
        perfMeasure("list:processAllColumns", "list:processAllColumns:start");

        Object.assign(this.optionalActiveFields, this.computeOptionalActiveFields());
        this.debugOpenView = this.opt.debugOpenView;

        perfMark("list:getActiveColumns:start");
        this.columns = this._toStableColumns(this.getActiveColumns());
        perfMeasure("list:getActiveColumns", "list:getActiveColumns:start");

        this.withHandleColumn = this.columns.some((col) => col.widget === "handle");

        this.gridState.update({
            list: this.props.list,
            columns: this.columns,
            hasSelectors: this.hasSelectors,
            hasOpenFormViewColumn: this.hasOpenFormViewColumn,
            hasActionsColumn: this.hasActionsColumn,
            showGroupAddLine: Boolean(this.props.editable && this.canCreate),
        });
        perfMark("list:gridState.rebuild:start");
        this.gridState.rebuild();
        perfMeasure("list:gridState.rebuild", "list:gridState.rebuild:start");

        perfMark("list:virt.refresh:start");
        this.virt.refresh();
        perfMeasure("list:virt.refresh", "list:virt.refresh:start");
    }

    /**
     * The shared surface handed to every list satellite hook, built once in
     * `setup`. A method rather than a literal inline for the same reason
     * `buildRowApi` is one: a renderer subclass extends the context by
     * overriding this and spreading `super.buildGridContext()`, which is not
     * possible against an object literal buried in `setup`.
     *
     * Every member is a lazy getter or a bound callback, so a hook built
     * BEFORE `this.sel` / `this.virt` / `this.gridState` exist still resolves
     * them at call time. Do not turn any of these into a plain value.
     *
     * @returns {import("./list_renderer").ListGridContext}
     */
    buildGridContext() {
        return {
            getProps: () => this.props,
            getEnv: () => this.env,
            getColumns: () => this.columns,
            getAllColumns: () => this.allColumns,
            getFields: () => this.fields,
            getGridState: () => this.gridState,
            getEditedRecord: () => this.editedRecord,
            getOptionalActiveFields: () => this.optionalActiveFields,
            getAllowSelectors: () => this.props.allowSelectors,
            getCanCreate: () => this.canCreate,
            getDisplayRowCreates: () => this.displayRowCreates,
            getControls: () => this.controls,
            getSel: () => this.sel,
            getVirtualization: () => this.virt,
            canResequence: () => this.canResequenceRows,
            toggleRecordSelection: (record) => this.toggleRecordSelection(record),
            onToggleGroup: (group) => this.toggleGroup(group),
            onAdd: (params) => this.add(params),
            onOpenRecord: (record) => this.props.openRecord(record),
            onDeleteRecord: (record) => this.onDeleteRecord(record),
            onEditNextRecord: (record, group) => this.editNextRecord(record, group),
            onSave: () => this.saveOptionalActiveFields(),
            findFocusFutureCell: (cell, cellIsInGroupRow, direction) =>
                this.findFocusFutureCell(cell, cellIsInGroupRow, direction),
            isInlineEditable: (record) => this.isInlineEditable(record),
            isCellReadonly: (column, record) => this.isCellReadonly(column, record),
            expandCheckboxes: (record, direction) =>
                this.sel.expandCheckboxes(
                    record,
                    /** @type {"up" | "down"} */ (direction),
                ),
        };
    }

    /**
     * Builds the {@link ListRowApi} shared by this renderer's record rows.
     * A subclass whose row template calls additional renderer methods extends
     * the returned object:
     *
     *     buildRowApi() {
     *         return {
     *             ...super.buildRowApi(),
     *             isSection: (record) => this.isSection(record),
     *         };
     *     }
     *
     * @returns {import("./list_renderer").ListRowApi}
     */
    buildRowApi() {
        const rec = (/** @type {any} */ r) => this.resolveRowRecord(r);
        const grp = (/** @type {any} */ g) => this.resolveRowGroup(g);
        return {
            // rendering reads: the row-context record argument passes through,
            // so what the method reads subscribes the calling row
            getRowClass: (record) => this.getRowClass(record),
            getColumns: (record) => this.getColumns(record),
            evalInvisible: (invisible, record) => this.evalInvisible(invisible, record),
            canUseFormatter: (column, record) => this.canUseFormatter(column, record),
            getFormattedValue: (column, record) =>
                this.getFormattedValue(column, record),
            getCellClass: (column, record) => this.getCellClass(column, record),
            getCellTitle: (column, record, formattedValue) =>
                this.getCellTitle(column, record, formattedValue),
            getFieldClass: (column) => this.getFieldClass(column),
            getFieldProps: (record, column) => this.getFieldProps(record, column),
            displayDeleteIcon: (record) => this.displayDeleteIcon(record),
            // action callbacks: record/group arguments are translated back to
            // this renderer's context so identity comparisons keep holding
            onCellClicked: (record, column, ev, newWindow) =>
                this.onCellClicked(rec(record), column, ev, newWindow),
            onButtonCellClicked: (record, column, ev) =>
                this.onButtonCellClicked(rec(record), column, ev),
            onRemoveCellClicked: (record, ev) =>
                this.onRemoveCellClicked(rec(record), ev),
            onCellKeydown: (ev, group = null, record = null) =>
                this.onCellKeydown(ev, grp(group), rec(record)),
            toggleRecordSelection: (record, ev) =>
                this.toggleRecordSelection(rec(record), rec(ev)),
            onRowTouchStart: (record, ev) => this.onRowTouchStart(rec(record), ev),
            onRowTouchEnd: (record) => this.onRowTouchEnd(rec(record)),
            onRowTouchMove: (record) => this.onRowTouchMove(rec(record)),
            onClickCapture: (record, ev) => this.onClickCapture(rec(record), ev),
            ignoreEventInSelectionMode: (ev) => this.ignoreEventInSelectionMode(ev),
            // row plumbing
            getGridState: () => this.gridState,
            getEditedRecord: () => this.editedRecord,
            displaySaveNotification: () => this.displaySaveNotification(),
            markRowRender: (recordId) => this.markRowRender(recordId),
        };
    }

    /**
     * The record rows' props: the explicit row context (see the class
     * comment on `ListRecordRow`, including the subclass extension recipe).
     * Values are identity-stable across renders unless the row's output
     * changed, so the `t-props` diff skips untouched rows; the cross-row
     * flips travel through the stable `flags` reactive instead of per-row
     * props.
     *
     * @param {RelationalRecord} record
     * @param {Group | undefined} group
     * @param {string | undefined} groupId
     */
    getRowProps(record, group, groupId) {
        return {
            record,
            group,
            groupId,
            list: this.props.list,
            archInfo: this.props.archInfo,
            readonly: this.props.readonly,
            onOpenFormView: this.props.onOpenFormView,
            api: this.rowApi,
            flags: this.rowFlags,
            recordRowTemplate: /** @type {any} */ (this.constructor).recordRowTemplate,
            columns: this.columns,
            activeActions: this.activeActions,
            isEdited: this.editedRecord === record,
            canResequence: this.canResequenceRows,
            hasSelectors: this.hasSelectors,
            hasOpenFormViewColumn: this.hasOpenFormViewColumn,
            displayOptionalFields: this.displayOptionalFields,
            isX2Many: this.isX2Many,
            rowIndex: this.gridState.findRowByRecordId(String(record.id))?.globalIndex,
        };
    }

    /**
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
        return !orderBy.length || orderBy[0].name === handleField;
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
            fields: this.props.list.fieldNames,
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
        viewIdentifier.push(...keyParts.fields.toSorted());
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

    get emptyRowIds() {
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
                    return;
                }
                this.focusCell(column);
                this.nav.cellToFocus = null;
            } else {
                const recordId = record.id;
                await this.resequencePromise;
                record =
                    this.props.list.records.find((r) => r.id === recordId) || record;
                if (await this.props.list.enterEditMode(record)) {
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

        const closestCell = /** @type {HTMLTableCellElement | null} */ (
            /** @type {HTMLElement} */ (ev.target).closest("td, th")
        );
        if (!closestCell) {
            return;
        }
        if (closestCell.querySelector(".o_select_menu [aria-expanded=true]")) {
            return;
        }

        if (this.nav.toggleFocusInsideCell(hotkey, closestCell)) {
            return;
        }

        const handled = this.editedRecord
            ? this.onCellKeydownEditMode(hotkey, closestCell, group, record)
            : this.onCellKeydownReadOnlyMode(hotkey, closestCell, group, record);

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
            const futureRecordId = futureRecord.id;
            // Claimed for the whole leave-then-enter, because this path cannot
            // delegate to `enterEditMode` (it needs the stricter
            // `leaveEditMode({ validate: true })`). Without the claim
            // `isEditing` drops to false between the two halves and every row
            // repaints twice — the Enter key cost 61 row renders on a 30-row
            // list where Tab, which does delegate, cost 4.
            // `enterEditMode` is RETURNED into the chain, not fired and
            // forgotten: `release` must not run until edition has landed, or
            // the gap it exists to close reopens just before the end.
            const release = list.beginEditHandover(futureRecord);
            list.leaveEditMode({ validate: true })
                .then((canProceed) => {
                    if (!canProceed) {
                        return;
                    }
                    const target =
                        list.records.find((r) => r.id === futureRecordId) ??
                        list.records[index + 1] ??
                        list.records.at(-1);
                    if (target) {
                        return list.enterEditMode(target);
                    }
                })
                .finally(release);
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
     * @returns {boolean}
     */
    onCellKeydownEditMode(hotkey, cell, group, record) {
        return this.nav.onCellKeydownEditMode(hotkey, cell, group, record);
    }

    /**
     * @param {string} hotkey
     * @param {HTMLTableCellElement} cell
     * @param {Group | null} group
     * @param {RelationalRecord | null} record
     * @returns {boolean}
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
        // `list.isEditing`, not `this.editedRecord`: this value is published to
        // every row through `rowFlags`, and each row subscribes to that one
        // key. `editedRecord` is transiently null while edition is handed from
        // one row to the next, which would flip this false -> true -> false and
        // re-render every row twice for a frame that is never painted.
        // `isEditing` spans the handover. See DynamicList#isEditing.
        return !this.props.list.isEditing && !this.props.list.model.useSampleModel;
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
        this.sel.toggleSelection(record, this.sel.shiftKeyMode);
    }

    /**
     * @param {string} fieldName
     */
    toggleOptionalField(fieldName) {
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
            return;
        }

        /** @type {HTMLElement} */ (this.tableRef.el)
            .querySelector("tbody")
            ?.classList.remove("o_keyboard_navigation");

        const target = /** @type {HTMLElement} */ (ev.target);
        if (this.state.showGroupInput && !target.closest(".o_list_group_input")) {
            this.state.showGroupInput = false;
        }
        if (
            /** @type {HTMLElement} */ (this.tableRef.el).contains(target) &&
            target.closest(".o_data_row")
        ) {
            return;
        }
        if (this.activeElement !== this.uiService.activeElement) {
            return;
        }
        if (target.closest(".o_datetime_picker")) {
            return;
        }
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
        if (!column.relatedPropertyField && this.tooltipInfoByColumn[column.id]) {
            return this.tooltipInfoByColumn[column.id];
        }
        const tooltipInfo = getTooltipInfo({
            viewMode: "list",
            resModel: this.props.list.resModel,
            field: this.fields[column.name],
            fieldInfo: /** @type {any} */ (column),
        });
        if (!column.relatedPropertyField) {
            this.tooltipInfoByColumn[column.id] = tooltipInfo;
        }
        return tooltipInfo;
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

/**
 * Installs a mixin onto the prototype AFTER the class body, so a name defined
 * in both would be silently won by the mixin — and the class body is where a
 * reader looks first. Collisions are refused instead: the fix is to rename, or
 * to drop the member from the mixin.
 *
 * @param {object} mixin
 * @param {string} name
 */
function installListRendererMixin(mixin, name) {
    const descriptors = Object.getOwnPropertyDescriptors(mixin);
    for (const key of Object.keys(descriptors)) {
        if (Object.hasOwn(ListRenderer.prototype, key)) {
            throw new Error(
                `${name} would override ListRenderer.prototype.${key} declared elsewhere`,
            );
        }
        descriptors[key].enumerable = false;
    }
    Object.defineProperties(ListRenderer.prototype, descriptors);
}
installListRendererMixin(listStylingMixin, "listStylingMixin");
installListRendererMixin(listGroupRenderingMixin, "listGroupRenderingMixin");
installListRendererMixin(listSortingMixin, "listSortingMixin");
