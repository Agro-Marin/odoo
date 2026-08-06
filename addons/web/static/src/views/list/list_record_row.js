// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_record_row */

import {
    Component,
    onRendered,
    onWillRender,
    reactive,
    status,
    toRaw,
} from "@odoo/owl";
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
 *   row template performs (directly or through a renderer method that
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
 * The class members below mirror the bare names the `recordRowTemplate`
 * family resolves on `this`, because the same template body must also keep
 * working when a subclass `Rows` template inlines it with `t-call` on the
 * RENDERER's context (project's notebook tasks, hr_skills) — bare names
 * resolve on either component.
 *
 * TRANSITIONAL (to be deleted once every downstream row template reads
 * through `api`/`props`): names outside the static surface still resolve
 * through the legacy delegation machinery — prototype accessors installed
 * from the renderer's own props and prototype chain, a Proxy substituting
 * `record`/`group`, and a shadow-reactive wrapper subscribing the row to
 * renderer state it reads. `warnUndelegatedRendererFields` (debug) flags
 * renderer fields assigned too late for delegation.
 */
export class ListRecordRow extends Component {
    static template = "web.ListRecordRow";
    static components = {};
    static props = ["*"];

    /** @type {Map} */
    _boundFns;
    /** @type {Map} */
    _dualCache;

    setup() {
        useRenderCounter("list.ListRecordRow");
        const row = this;
        const renderer = this.props.renderer;
        /** @type {Map<string, Function>} */
        this._boundFns = new Map();
        /** @type {Map<string, {target: any, proxy: any}>} */
        this._dualCache = new Map();
        this._isRendering = false;
        const weakRow = new WeakRef(this);
        this._shadowRender = () => {
            const liveRow = weakRow.deref();
            if (liveRow && status(liveRow) !== "destroyed") {
                liveRow.render();
            }
        };
        this._rendererCtx = new Proxy(renderer, {
            get(target, key) {
                if (key === "record") {
                    return row.record;
                }
                if (key === "group") {
                    return row.group;
                }
                if (key === "groupId") {
                    return row.props.groupId;
                }
                return Reflect.get(target, key, row._rendererCtx);
            },
            set(target, key, value) {
                return Reflect.set(target, key, value);
            },
        });
        installRendererDelegation(/** @type {any} */ (this.constructor), renderer);
        onWillRender(() => {
            this._isRendering = true;
            if (odoo.debug) {
                warnUndelegatedRendererFields(
                    /** @type {any} */ (this.constructor),
                    renderer,
                );
            }
            installRendererDelegation(/** @type {any} */ (this.constructor), renderer);
            this.props.api.markRowRender(String(this.props.record.id));
        });
        onRendered(() => {
            this._isRendering = false;
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

    // -------------------------------------------------------------------------
    // TRANSITIONAL legacy delegation (names outside the static surface)
    // -------------------------------------------------------------------------

    /**
     * @param {string} name
     */
    _delegateGet(name) {
        const value = this._rendererCtx[name];
        if (typeof value === "function") {
            let fn = this._boundFns.get(name);
            if (!fn) {
                const ctx = this._rendererCtx;
                fn = (...args) => ctx[name](...args);
                this._boundFns.set(name, fn);
            }
            return fn;
        }
        if (
            this._isRendering &&
            value !== null &&
            typeof value === "object" &&
            toRaw(value) !== value
        ) {
            return this._subscribingWrapper(name, value);
        }
        return value;
    }

    /**
     * @param {string} name
     * @param {any} value
     */
    _subscribingWrapper(name, value) {
        const cached = this._dualCache.get(name);
        if (cached && cached.target === value) {
            return cached.proxy;
        }
        const shadow = reactive(toRaw(value), this._shadowRender);
        const proxy = new Proxy(value, {
            get(target, key) {
                if (typeof key !== "symbol") {
                    try {
                        void shadow[key];
                    } catch (error) {
                        if (odoo.debug) {
                            console.warn(
                                `ListRecordRow: reading "${String(key)}" on "${name}" threw while subscribing`,
                                error,
                            );
                        }
                    }
                }
                return Reflect.get(target, key);
            },
        });
        this._dualCache.set(name, { target: value, proxy });
        return proxy;
    }
}

const SKIP_DELEGATION = new Set(["constructor", "props", "env", "__owl__"]);

/**
 * @param {any} RowClass
 * @param {any} renderer
 */
function installRendererDelegation(RowClass, renderer) {
    if (!Object.hasOwn(RowClass, "_delegatedNames")) {
        RowClass._delegatedNames = new Set();
    }
    const installed = RowClass._delegatedNames;
    const install = (/** @type {string} */ name) => {
        if (installed.has(name)) {
            return;
        }
        installed.add(name);
        if (SKIP_DELEGATION.has(name) || name in RowClass.prototype) {
            return;
        }
        Object.defineProperty(RowClass.prototype, name, {
            configurable: true,
            enumerable: false,
            get() {
                return this._delegateGet(name);
            },
            set(value) {
                this.props.renderer[name] = value;
            },
        });
    };
    for (const name of Object.getOwnPropertyNames(renderer)) {
        install(name);
    }
    let proto = Object.getPrototypeOf(renderer);
    while (proto && proto !== Component.prototype && proto !== Object.prototype) {
        for (const name of Object.getOwnPropertyNames(proto)) {
            install(name);
        }
        proto = Object.getPrototypeOf(proto);
    }
}

/**
 * @param {any} RowClass
 * @param {any} renderer
 */
function warnUndelegatedRendererFields(RowClass, renderer) {
    const installed = RowClass._delegatedNames;
    if (!installed) {
        return;
    }
    for (const name of Object.getOwnPropertyNames(renderer)) {
        if (!installed.has(name)) {
            if (!Object.hasOwn(RowClass, "_warnedUndelegatedNames")) {
                RowClass._warnedUndelegatedNames = new Set();
            }
            if (!RowClass._warnedUndelegatedNames.has(name)) {
                RowClass._warnedUndelegatedNames.add(name);
                console.warn(
                    `ListRecordRow: renderer field "${name}" was assigned after ` +
                        `row delegation accessors were installed; row templates ` +
                        `reading "${name}" resolve to undefined. Initialize the ` +
                        `field in the renderer's setup() so it is delegated.`,
                );
            }
        }
    }
}

/** @type {WeakMap<any, any>} */
const rowClassRegistry = new WeakMap();

/**
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
