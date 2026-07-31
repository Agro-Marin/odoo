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

const SKIP_DELEGATION = new Set(["constructor", "props", "env", "__owl__"]);

/** @extends Component */
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
            renderer.markRowRender?.(String(this.props.record.id));
            this._touchRecordDependencies();
        });
        onRendered(() => {
            this._isRendering = false;
        });
    }

    get record() {
        return resolveFlatRow(this)?.record ?? this.props.record;
    }

    get group() {
        return resolveFlatRow(this)?.parentGroup ?? this.props.group ?? undefined;
    }

    get groupId() {
        return this.props.groupId;
    }

    get _canSelectRecord() {
        return this.props.canSelectRecord;
    }

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
 * @param {any} row
 * @returns {any}
 */
function resolveFlatRow(row) {
    const gridState = row.props.renderer.gridState;
    if (!gridState) {
        return undefined;
    }
    const recordId = row.props.record.id;
    if (
        row._flatRowGeneration !== gridState.generation ||
        row._flatRowId !== recordId
    ) {
        row._flatRowGeneration = gridState.generation;
        row._flatRowId = recordId;
        row._flatRowValue = gridState.findRowByRecordId(String(recordId));
    }
    return row._flatRowValue;
}

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
