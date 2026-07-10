// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_record_row - Per-record row component isolating row renders from ListRenderer */

/**
 * ``ListRecordRow`` renders one ``<tr class="o_data_row">`` of the list view.
 *
 * Why a component (and not the historical ``t-call``): with a ``t-call``, every
 * cell expression of every visible row is re-evaluated on ANY reactive change
 * the renderer is subscribed to (a single checkbox toggle re-formatted every
 * cell of every row). As a component whose props are referentially stable for
 * unchanged rows, OWL's ``arePropsDifferent`` check skips the whole row —
 * only the row whose own record changed re-renders (same pattern as
 * ``ListAggregatesRow``, pinned by test R4).
 *
 * COMPATIBILITY CONTRACT — this extraction must be invisible to the ~15
 * addons that customize record rows (audited fork-wide 2026-07-02, see the
 * list below). They do it three ways, all preserved:
 *
 * 1. ``static recordRowTemplate = "..."`` on a ``ListRenderer`` subclass, with
 *    a template inheriting ``web.ListRenderer.RecordRow`` (account, website,
 *    purchase_requisition, resource, sale, sale_management, hr_skills(+slides),
 *    documents, account_online_synchronization, account_accountant,
 *    web_studio). The row body therefore STAYS at t-name
 *    ``web.ListRenderer.RecordRow`` (byte-identical, all xpath anchors intact);
 *    this component's own template is a thin wrapper that dynamically t-calls
 *    ``props.recordRowTemplate`` (the renderer's ``constructor.recordRowTemplate``).
 *
 * 2. ``this.X`` / bare-name expressions inside those templates historically
 *    resolved against the RENDERER's render context (its methods, getters,
 *    instance state — e.g. ``isSection(record)``, ``this.rightPanelState``,
 *    ``this.comboColumns``, ``getPreviousRecords(record)``) plus template-scope
 *    vars (``record``, ``group``, ``groupId``, ``_canSelectRecord``). The
 *    component emulates that context exactly:
 *      - every renderer member (own fields + full prototype chain, subclasses
 *        included) is delegated lazily through accessors installed on the row
 *        class prototype;
 *      - methods run with ``this`` set to a proxy over the renderer that also
 *        resolves ``record``/``group``/``groupId`` to this row's values — so
 *        renderer methods (and their ``super`` chains) behave exactly as when
 *        they ran inside the row ``t-call`` (e.g. account's
 *        ``isSection(record = this.record)`` default still works);
 *      - writes (``this.foo = x``) land on the renderer instance.
 *
 * 3. ``rowsTemplate`` overrides that still ``t-call`` ``constructor.recordRowTemplate``
 *    directly (project notebook tasks, hr_skills skills/resume). That legacy
 *    path is untouched: the row body template still renders fine with the
 *    renderer as ``this`` because no helper moved off the renderer.
 *
 * REACTIVITY DESIGN (verified against OWL semantics — subscriptions accrue to
 * the component whose reactive proxy performs the read):
 *
 * - ``record``/``group`` exposed to the template are the RENDERER's reactive
 *   proxies (recovered via ``gridState``), NOT the row-wrapped prop. This keeps
 *   proxy identity consistent with all renderer-side state (``editedRecord``
 *   comparisons, ``list.records.indexOf(record)``, account's
 *   ``parentSectionMap.get(record)``, documents'
 *   ``record === this.rightPanelState.focusedRecord``, selection ranges…).
 *   Renderer-level subscriptions therefore stay exactly as before.
 * - The row subscribes ITSELF through its OWL-wrapped ``props.record`` proxy in
 *   ``_touchRecordDependencies()`` (selection, edition, validity, field values,
 *   x2many content, eval context incl. ``parent.*``) — so a change to this
 *   record re-renders this row even when every other row is skipped.
 * - Renderer state read from row templates (e.g. documents'
 *   ``rightPanelState``) is wrapped during render so the row ALSO subscribes
 *   to it (shallow), while returned values keep renderer-proxy identity.
 */

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
 * Names that must never be delegated to the renderer: they belong to this
 * component instance (OWL internals + own props/env).
 */
const SKIP_DELEGATION = new Set(["constructor", "props", "env", "__owl__"]);

/** @extends Component */
export class ListRecordRow extends Component {
    static template = "web.ListRecordRow";
    // Filled per renderer class by ``getRowComponentClass`` with the RENDERER's
    // components, so sub-component resolution inside the row body is identical
    // to the historical t-call (which resolved through the renderer class).
    static components = {};
    // The row receives the renderer's own props spread in (so ``props.X``
    // expressions from inheriting templates — ``props.readonly``,
    // ``props.subsections``, ``props.hidePrices``, ``props.archInfo`` … — keep
    // resolving) plus per-row keys. Arbitrary keys ⇒ no closed schema.
    static props = ["*"];

    setup() {
        useRenderCounter("list.ListRecordRow");
        const row = this;
        const renderer = this.props.renderer;
        /** @type {Map<string, Function>} */
        this._boundFns = new Map();
        /** @type {Map<string, {target: any, proxy: any}>} */
        this._dualCache = new Map();
        this._isRendering = false;
        /** Render callback for shadow subscriptions of delegated renderer state. */
        this._shadowRender = () => {
            if (status(this) !== "destroyed") {
                this.render();
            }
        };
        /**
         * ``this`` emulation for delegated renderer members: behaves like the
         * historical template render context — renderer members + this row's
         * ``record``/``group``/``groupId``. Getters run with the proxy as
         * receiver (so e.g. account's ``get hidePrices() { return
         * this.record.data.… }`` sees this row's record); writes go through to
         * the renderer instance.
         */
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
            // Per-record cache invalidation: when this row re-renders without a
            // full renderer render, renderer-side per-render caches keyed by
            // (column, record) may hold stale entries for this record.
            renderer.markRowRender?.(String(this.props.record.id));
            this._touchRecordDependencies();
        });
        onRendered(() => {
            this._isRendering = false;
        });
    }

    /**
     * The record as the RENDERER's reactive proxy (identity-consistent with
     * all renderer-side comparisons/collections). ``gridState`` materializes
     * flat rows from the renderer's own ``props.list`` proxy, so the stored
     * record IS the renderer-callback proxy.
     */
    get record() {
        const props = this.props;
        const flat = props.renderer.gridState?.findRowByRecordId(
            String(props.record.id),
        );
        return flat?.record ?? props.record;
    }

    /**
     * Matches the historical template scope: the enclosing group in the
     * grouped non-virtualized branch, ``undefined`` in the virtualized branch
     * (which only ever set ``groupId``) and for ungrouped lists.
     */
    get group() {
        const renderer = this.props.renderer;
        if (renderer.virt?.isActive) {
            return undefined;
        }
        const flat = renderer.gridState?.findRowByRecordId(
            String(this.props.record.id),
        );
        return flat?.parentGroup ?? undefined;
    }

    /** Historical ``t-set`` scope var from the grouped rows recursion. */
    get groupId() {
        return this.props.groupId;
    }

    /** Historical ``t-set`` scope var from the root ``web.ListRenderer`` template. */
    get _canSelectRecord() {
        return this.props.canSelectRecord;
    }

    /**
     * Delegated member resolution (see class doc). Methods are wrapped so they
     * run against ``_rendererCtx`` (virtual dispatch through the renderer's
     * prototype chain, with this row's template vars available on ``this``).
     * During render, reactive renderer state is wrapped to also subscribe this
     * row (shallow) while preserving renderer-proxy identity of read values.
     *
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
     * Wrap a delegated reactive object so reads during this row's render also
     * subscribe THIS row (via a shadow proxy on the row's render callback)
     * while returning the untouched renderer-proxy values (identity-safe for
     * ``===`` comparisons, e.g. documents' ``rightPanelState.focusedRecord``).
     *
     * @param {string} name
     * @param {any} value reactive (OWL-proxied) object owned by the renderer
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
                    } catch {
                        // best-effort subscription only
                    }
                }
                return Reflect.get(target, key);
            },
        });
        this._dualCache.set(name, { target: value, proxy });
        return proxy;
    }

    /**
     * Subscribe this row to everything its DOM can depend on, through the
     * row's own reactive proxy (``props.record`` is auto-wrapped by OWL for
     * this component). This is what makes a single-record change re-render
     * ONLY this row. Read set mirrors what the row template + styling helpers
     * read: selection/edition/new state, per-field values (plus x2many
     * content counters), per-field validity, and the eval context used by
     * decoration/required/readonly/invisible expressions (including the
     * ``parent.*`` chain for x2many rows).
     */
    _touchRecordDependencies() {
        const record = this.props.record;
        void record.selected;
        void record.isInEdition;
        void record.isNew;
        const data = record.data;
        for (const fieldName in data) {
            const value = data[fieldName];
            void record.isFieldInvalid(fieldName);
            if (value !== null && typeof value === "object" && toRaw(value) !== value) {
                void (/** @type {any} */ (value).count);
                void (/** @type {any} */ (value).currentIds);
            }
        }
        let evalContext = record.evalContextWithVirtualIds;
        for (
            let depth = 0;
            evalContext && typeof evalContext === "object" && depth < 5;
            depth++
        ) {
            for (const key in evalContext) {
                if (key !== "parent") {
                    void evalContext[key];
                }
            }
            evalContext = /** @type {any} */ (evalContext).parent;
        }
    }
}

/**
 * Install lazy delegation accessors for every renderer member (own instance
 * fields + prototype chain up to, and excluding, ``Component.prototype``) that
 * the row class does not define itself. Installed once per (row class, name);
 * idempotent and shared by all instances of the same renderer class.
 *
 * @param {any} RowClass concrete row class (one per renderer class)
 * @param {any} renderer renderer instance (fully set up)
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
            // Non-enumerable so OWL's context-capture paths do not iterate
            // over these accessors (same constraint as the renderer mixins).
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

/** @type {WeakMap<any, any>} renderer class → row component class */
const rowClassRegistry = new WeakMap();

/**
 * Row component class for a given renderer class. Derived (and cached) per
 * renderer class so that sub-component resolution inside the row body uses the
 * RENDERER's ``static components`` — exactly what the historical ``t-call``
 * resolved against. Prototype patches on ``ListRecordRow`` (e.g. in tests)
 * are inherited by every derived class.
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
        RowClass.components = { ...RendererClass.components };
        rowClassRegistry.set(RendererClass, RowClass);
    }
    return RowClass;
}
