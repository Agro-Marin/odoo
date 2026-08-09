// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_record_row */

import { Component, onWillRender } from "@odoo/owl";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";

/**
 * @typedef {import("./list_renderer").ListRowApi} ListRowApi
 * @typedef {import("./list_renderer").ListRowFlags} ListRowFlags
 */

/**
 * One rendered record row.
 *
 * The row receives an explicit row context from `ListRenderer.getRowProps`:
 *
 * - `record` / `group` / `groupId`: THIS row's data. `props.record` is the
 *   reactive the framework re-targets to this component, so every read the
 *   row template performs (directly, or through a renderer method that
 *   receives `record` as an argument) subscribes THIS row — the template's
 *   actual reads define the row's re-render triggers.
 * - `api` {@link ListRowApi}: bound callbacks routing through the renderer
 *   instance, so renderer-subclass overrides keep catching the calls.
 *   Action callbacks resolve their record/group arguments back to the
 *   renderer's reactivity context (see `ListRenderer.resolveRowRecord`), so
 *   identity comparisons in the renderer and the model keep holding.
 * - `flags` {@link ListRowFlags}: ONE stable reactive object carrying the
 *   cross-row booleans; a row that reads a flag subscribes to exactly that
 *   key, so a flip re-renders the rows whose output depends on it and no
 *   others.
 * - the remaining props (`columns`, `rowIndex`, `isEdited`, `canResequence`,
 *   `hasSelectors`, ...) are the per-render invalidation keys: `t-props`
 *   diffing skips the row when they are all identical.
 *
 * Extension recipe for a renderer subclass whose row template needs more:
 * expose methods with a `buildRowApi()` extension (called as `api.x(...)`
 * in the template) and pass state or derivations with a `getRowProps()`
 * extension (read as `props.x`). A per-row derivation whose inputs live
 * OUTSIDE the row's own record (e.g. a parent section's collapse state)
 * belongs in `getRowProps`: computing it there subscribes the renderer to
 * the foreign inputs and prop-flips exactly the affected rows.
 *
 * The class members below mirror the bare names the base
 * `web.ListRenderer.RecordRow` body resolves on `this`, because the same
 * body must also keep working when a subclass `Rows` template inlines it
 * with `t-call` on the RENDERER's context (project's notebook tasks,
 * hr_skills) — bare names resolve on either component.
 */
/**
 * The row context {@link ListRenderer#getRowProps} builds, as an OWL schema.
 *
 * The contract was already written down — {@link ListRowApi} and
 * {@link ListRowFlags} above, plus the prose on this class — and none of it was
 * executable, so `getRowProps` and the row template could drift apart in
 * silence. The row is instantiated once per record, which is the seam where a
 * quiet mismatch is most expensive to trace: a `t-props` typo shows up as one
 * column rendering blank in one view, not as an error.
 *
 * `"*": true` is required, not laziness: the documented extension recipe for a
 * renderer subclass is to add keys in a `getRowProps()` override and read them
 * as `props.x`, and roughly forty subclasses exist. The declared entries are the
 * ones the base renderer always supplies.
 *
 * `api` and `flags` are checked for shape rather than by key. Their members are
 * enumerated in the typedefs, but a subclass extends both, and OWL's nested
 * `shape` is closed — validating them key-by-key would reject exactly the
 * extension the recipe asks for.
 */
export const listRecordRowProps = {
    // this row's data
    record: { type: Object },
    group: { type: [Object, { value: null }, { value: false }], optional: true },
    groupId: { type: [String, Number, { value: false }], optional: true },

    // the shared row interface
    api: { type: Object },
    flags: { type: Object },

    // the list this row belongs to, and how it was configured
    list: { type: Object },
    archInfo: { type: Object },
    columns: { type: Array },
    activeActions: { type: Object, optional: true },
    recordRowTemplate: { type: String, optional: true },
    onOpenFormView: { type: Function, optional: true },

    // per-render invalidation keys: `t-props` diffing skips the row when these
    // are all identical, so each one is a deliberate re-render trigger
    readonly: { type: Boolean, optional: true },
    isEdited: { type: Boolean },
    canResequence: { type: Boolean },
    hasSelectors: { type: Boolean },
    hasOpenFormViewColumn: { type: Boolean },
    displayOptionalFields: { type: Boolean },
    isX2Many: { type: Boolean },
    // undefined while the grid state has not placed the row yet
    rowIndex: { type: Number, optional: true },

    "*": true,
};

export class ListRecordRow extends Component {
    static template = "web.ListRecordRow";
    static components = {};
    static props = listRecordRowProps;

    setup() {
        useRenderCounter("list.ListRecordRow");
        onWillRender(() => {
            this.props.api.markRowRender(String(this.props.record.id));
        });
    }

    // -------------------------------------------------------------------------
    // Row context: data
    // -------------------------------------------------------------------------

    get record() {
        return this.props.record;
    }

    get group() {
        return this.props.group;
    }

    get groupId() {
        return this.props.groupId;
    }

    // -------------------------------------------------------------------------
    // Row context: api and flags
    // -------------------------------------------------------------------------

    /** @returns {ListRowApi} */
    get api() {
        return this.props.api;
    }

    /** @returns {ListRowFlags} */
    get flags() {
        return this.props.flags;
    }

    get _canSelectRecord() {
        return this.props.flags.canSelectRecord;
    }

    get editedRecord() {
        return this.props.flags.hasEditedRecord
            ? this.props.api.getEditedRecord()
            : null;
    }

    get gridState() {
        return this.props.api.getGridState();
    }

    get _displaySaveNotification() {
        return this.props.api.displaySaveNotification;
    }

    // -------------------------------------------------------------------------
    // Row context: view-shape flags mirrored from props for bare-name reads
    // -------------------------------------------------------------------------

    get hasSelectors() {
        return this.props.hasSelectors;
    }

    get hasOpenFormViewColumn() {
        return this.props.hasOpenFormViewColumn;
    }

    get displayOptionalFields() {
        return this.props.displayOptionalFields;
    }

    get isX2Many() {
        return this.props.isX2Many;
    }

    get activeActions() {
        return this.props.activeActions;
    }

    // -------------------------------------------------------------------------
    // Row context: rendering reads (row-context record argument subscribes
    // this row to exactly what the callee reads)
    // -------------------------------------------------------------------------

    /** @param {any} record */
    getRowClass(record) {
        return this.props.api.getRowClass(record);
    }

    /** @param {any} record */
    getColumns(record) {
        return this.props.api.getColumns(record);
    }

    /**
     * @param {string} invisible
     * @param {any} record
     */
    evalInvisible(invisible, record) {
        return this.props.api.evalInvisible(invisible, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     */
    canUseFormatter(column, record) {
        return this.props.api.canUseFormatter(column, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     */
    getFormattedValue(column, record) {
        return this.props.api.getFormattedValue(column, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     */
    getCellClass(column, record) {
        return this.props.api.getCellClass(column, record);
    }

    /**
     * @param {any} column
     * @param {any} record
     * @param {string} [formattedValue]
     */
    getCellTitle(column, record, formattedValue) {
        return this.props.api.getCellTitle(column, record, formattedValue);
    }

    /** @param {any} column */
    getFieldClass(column) {
        return this.props.api.getFieldClass(column);
    }

    /**
     * @param {any} record
     * @param {any} column
     */
    getFieldProps(record, column) {
        return this.props.api.getFieldProps(record, column);
    }

    /** @param {any} record */
    displayDeleteIcon(record) {
        return this.props.api.displayDeleteIcon(record);
    }

    // -------------------------------------------------------------------------
    // Row context: action callbacks (record/group arguments are resolved back
    // to the renderer's context at the api boundary)
    // -------------------------------------------------------------------------

    /**
     * @param {any} record
     * @param {any} column
     * @param {PointerEvent} ev
     * @param {boolean} [newWindow]
     */
    onCellClicked(record, column, ev, newWindow) {
        return this.props.api.onCellClicked(record, column, ev, newWindow);
    }

    /**
     * @param {any} record
     * @param {any} column
     * @param {PointerEvent} ev
     */
    onButtonCellClicked(record, column, ev) {
        return this.props.api.onButtonCellClicked(record, column, ev);
    }

    /**
     * @param {any} record
     * @param {PointerEvent} ev
     */
    onRemoveCellClicked(record, ev) {
        return this.props.api.onRemoveCellClicked(record, ev);
    }

    /**
     * @param {KeyboardEvent} ev
     * @param {any} [group]
     * @param {any} [record]
     */
    onCellKeydown(ev, group = null, record = null) {
        return this.props.api.onCellKeydown(ev, group, record);
    }

    /**
     * @param {any} record
     * @param {any} [ev]
     */
    toggleRecordSelection(record, ev) {
        return this.props.api.toggleRecordSelection(record, ev);
    }

    /**
     * @param {any} record
     * @param {TouchEvent} ev
     */
    onRowTouchStart(record, ev) {
        return this.props.api.onRowTouchStart(record, ev);
    }

    /** @param {any} record */
    onRowTouchEnd(record) {
        return this.props.api.onRowTouchEnd(record);
    }

    /** @param {any} record */
    onRowTouchMove(record) {
        return this.props.api.onRowTouchMove(record);
    }

    /**
     * @param {any} record
     * @param {PointerEvent} ev
     */
    onClickCapture(record, ev) {
        return this.props.api.onClickCapture(record, ev);
    }

    /** @param {MouseEvent} ev */
    ignoreEventInSelectionMode(ev) {
        return this.props.api.ignoreEventInSelectionMode(ev);
    }
}

/** @type {WeakMap<any, any>} */
const rowClassRegistry = new WeakMap();

/**
 * Derives (and caches) the row component class for a renderer class. The
 * subclass exists so `t-component`'s static component lookup sees the
 * RENDERER's `components` — a subclass row template may instantiate
 * components the base row never heard of — as a live view, not a snapshot.
 *
 * @param {any} RendererClass
 * @returns {typeof ListRecordRow}
 */
export function getRowComponentClass(RendererClass) {
    let RowClass = rowClassRegistry.get(RendererClass);
    if (!RowClass) {
        RowClass = class extends ListRecordRow {};
        Object.defineProperty(RowClass, "name", {
            value: `ListRecordRow_${RendererClass.name}`,
            configurable: true,
        });
        Object.defineProperty(RowClass, "components", {
            configurable: true,
            get() {
                return RendererClass.components;
            },
            set(value) {
                Object.defineProperty(this, "components", {
                    value,
                    writable: true,
                    configurable: true,
                    enumerable: true,
                });
            },
        });
        rowClassRegistry.set(RendererClass, RowClass);
    }
    return RowClass;
}
