// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/relational_model - Top-level data model orchestrating records, groups, and lists with ORM loading and onchange */

import { EventBus, markRaw, toRaw } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { ModelEvent } from "@web/core/events";
import { modelLog } from "@web/core/utils/asset_log";
import { deepCopy } from "@web/core/utils/collections/objects";
import { Deferred, KeepLast, Mutex } from "@web/core/utils/concurrency";
import { orderByToString } from "@web/core/utils/order_by";
import { Model } from "@web/model/model";

import { cloneGroupTree, computeNextConfig } from "./config_transitions.js";
import { DynamicGroupList } from "./dynamic_group_list.js";
import { DynamicRecordList } from "./dynamic_record_list.js";
import { FetchRecordError } from "./errors.js";
import { getBasicEvalContext, getId } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";
import { invalidateAggregateSpecs } from "./field_values.js";
import { Group } from "./group.js";
import { postprocessReadGroup } from "./group_postprocessor.js";
import { buildWebReadGroupParams } from "./read_group_builder.js";
import { RelationalRecord } from "./record.js";
import { SpecialDataCache } from "./special_data_cache.js";
import { StaticList } from "./static_list.js";
import { UrgentSaveCoordinator } from "./urgent_save_coordinator.js";

/** @import { Context } from "@web/core/context" */
/** @import { DomainListRepr } from "@web/core/domain" */
/** @import { Field, FieldInfo, SearchParams } from "@web/model/types" */
/** @import { ServiceFactories as Services } from "services" */
/** @import { DataPoint } from "./datapoint.js" */

/**
 * @typedef {{
 *  changes?: Record<string, any>;
 *  fieldNames?: string[];
 *  evalContext?: any;
 *  onError?: (error: unknown) => unknown;
 *  cache?: Object;
 *  [key: string]: any;
 * }} OnChangeParams
 *
 * @typedef {SearchParams & {
 *  fields: Record<string, Field>;
 *  activeFields: Record<string, FieldInfo>;
 *  fieldsToAggregate: string[];
 *  isMonoRecord: boolean;
 *  isRoot: boolean;
 *  resIds?: number[];
 *  mode?: "edit" | "readonly";
 *  loadId?: string;
 *  limit?: number;
 *  offset?: number;
 *  countLimit?: number;
 *  groupsLimit?: number;
 *  groups?: Record<string, unknown>;
 *  currentGroups?: Record<string, unknown>;
 *  openGroupsByDefault?: boolean;
 *  extraDomain?: import("@web/core/domain").DomainListRepr;
 *  isFolded?: boolean;
 *  isGroupList?: boolean;
 *  rawContext?: Record<string, unknown>;
 *  [key: string]: any;
 * }} RelationalModelConfig
 *
 * @typedef {{
 *  config: RelationalModelConfig;
 *  state?: RelationalModelState;
 *  hooks?: { lifecycle?: Partial<LifecycleHooks>; ui?: Partial<UIHooks> };
 *  limit?: number;
 *  countLimit?: number;
 *  groupsLimit?: number;
 *  defaultOrderBy?: import("@web/core/utils/order_by").OrderTerm[];
 *  maxGroupByDepth?: number;
 *  multiEdit?: boolean;
 *  groupByInfo?: Record<string, { activeFields: Record<string, FieldInfo>; fields: Record<string, Field> }>;
 *  activeIdsLimit?: number;
 *  useSendBeaconToSaveUrgently?: boolean;
 * }} RelationalModelParams
 *
 * @typedef {{
 *  config: RelationalModelConfig;
 *  specialDataCaches: import("./special_data_cache.js").SpecialDataCache;
 * }} RelationalModelState
 */

/**
 * Lifecycle hooks — model-emitted notifications about its own state.
 *
 * Some return values are load-bearing: ``onWillSaveRecord`` /
 * ``onWillSaveMulti`` can veto (return ``false``); ``onAskMultiSaveConfirmation``
 * returns the user's confirmation choice. The rest are fire-and-forget.
 *
 * @typedef {{
 *  onWillLoadRoot: (config: RelationalModelConfig) => any;
 *  onRootLoaded: (root: DataPoint) => any;
 *  onWillSaveRecord: (record: RelationalRecord, changes: Record<string, unknown>) => any;
 *  onRecordSaved: (record: RelationalRecord, changes: Record<string, unknown>) => any;
 *  onWillSaveMulti: (record: RelationalRecord, changes: Object) => any;
 *  onSavedMulti: (records: RelationalRecord[]) => any;
 *  onWillSetInvalidField: (record: RelationalRecord, fieldName: string) => any;
 *  onRecordChanged: (record: RelationalRecord, changes: Record<string, unknown>) => any;
 *  onWillDisplayOnchangeWarning: (warning: Object) => any;
 *  onAskMultiSaveConfirmation: (changes: Object, validRecords: RelationalRecord[]) => any;
 * }} LifecycleHooks
 */
export const DEFAULT_LIFECYCLE_HOOKS = /** @type {LifecycleHooks} */ ({
    onWillLoadRoot: () => {},
    onRootLoaded: () => {},
    onWillSaveRecord: () => {},
    onRecordSaved: () => {},
    onWillSaveMulti: () => {},
    onSavedMulti: () => {},
    onWillSetInvalidField: () => {},
    onRecordChanged: () => {},
    onWillDisplayOnchangeWarning: () => {},
    onAskMultiSaveConfirmation: () => true,
});

/**
 * UI hooks — model requests for controller-mediated UI side effects.
 *
 * Controllers wire these via ``makeModelUIHooks()`` in ``views/view_utils``
 * so the model layer never imports ``dialog`` / ``notification`` / ``action``
 * services directly. Return values are either ``undefined`` or a
 * "close-this-notification" callback (``onDisplayInvalidFields``,
 * ``onDisplayUrgentSave``) — the model never branches on them otherwise.
 *
 * @typedef {{
 *  onDisplayOnchangeWarning: (warning: {type: string, title: string, message: string, className?: string, sticky?: boolean}) => void;
 *  onDisplayInvalidFields: () => (() => void);
 *  onDisplayUrgentSave: (message: string) => (() => void);
 *  onDisplayPropertyWarning: (message: string) => void;
 *  onDisplayArchiveAction: (action: Object, reload: () => Promise<any>) => any;
 *  onConfirmArchive: (isSelected: boolean, archiveFn: Function, unarchiveFn: Function, dialogProps?: Object) => void;
 *  onConfirmDuplicate: (resIds: number[], copyFn: Function) => void;
 *  onDisplayLimitNotification: (msg: string) => void;
 * }} UIHooks
 */
export const DEFAULT_UI_HOOKS = /** @type {UIHooks} */ ({
    onDisplayOnchangeWarning: () => {},
    onDisplayInvalidFields: () => () => {},
    onDisplayUrgentSave: () => () => {},
    onDisplayPropertyWarning: () => {},
    onDisplayArchiveAction: (_action, reload) => reload(),
    onConfirmArchive: (_isSelected, archiveFn) => archiveFn(),
    onConfirmDuplicate: (resIds, copyFn) => copyFn(resIds),
    onDisplayLimitNotification: () => {},
});

export class RelationalModel extends Model {
    static services = ["orm"];
    static Record = RelationalRecord;
    static Group = Group;
    static DynamicRecordList = DynamicRecordList;
    static DynamicGroupList = DynamicGroupList;
    static StaticList = StaticList;
    static DEFAULT_LIMIT = 80;
    static DEFAULT_COUNT_LIMIT = 10000;
    static DEFAULT_GROUP_LIMIT = 80;
    static DEFAULT_OPEN_GROUP_LIMIT = 10;
    static withCache = true;

    /** @returns {typeof RelationalModel} */
    get Class() {
        return /** @type {typeof RelationalModel} */ (this.constructor);
    }

    /**
     * @param {RelationalModelParams} params
     * @param {Object} _services
     */
    setup(params, _services) {
        this.bus = new EventBus();

        this.keepLast = markRaw(new KeepLast());
        this.countKeepLast = markRaw(new KeepLast());
        this.mutex = markRaw(new Mutex());

        /** @type {RelationalModelConfig} */
        this.config = {
            isMonoRecord: false,
            context: {},
            fieldsToAggregate: Object.keys(params.config.activeFields),
            ...params.config,
            isRoot: true,
        };

        this.hooks = {
            lifecycle: { ...DEFAULT_LIFECYCLE_HOOKS, ...params.hooks?.lifecycle },
            ui: { ...DEFAULT_UI_HOOKS, ...params.hooks?.ui },
        };
        this.hasOnRecordChangedHook =
            this.hooks.lifecycle.onRecordChanged !==
            DEFAULT_LIFECYCLE_HOOKS.onRecordChanged;

        this.initialLimit = params.limit || this.Class.DEFAULT_LIMIT;
        this.initialGroupsLimit = params.groupsLimit;
        this.initialCountLimit = params.countLimit || this.Class.DEFAULT_COUNT_LIMIT;
        this.defaultOrderBy = params.defaultOrderBy;
        this.maxGroupByDepth = params.maxGroupByDepth;
        this.groupByInfo = params.groupByInfo || {};
        this.multiEdit = params.multiEdit;
        this.activeIdsLimit = params.activeIdsLimit || Number.MAX_SAFE_INTEGER;
        this.specialDataCaches = markRaw(
            params.state?.specialDataCaches || new SpecialDataCache(),
        );
        this.useSendBeaconToSaveUrgently = params.useSendBeaconToSaveUrgently || false;
        this.withCache = this.Class.withCache && this.env.config?.cache;
        this.initialSampleGroups = undefined;
        this.canUseSampleModel = Boolean(params.canUseSampleModel);

        /**
         * Observable urgent-save mode state.  When ``urgentSave.isActive``
         * is true, downstream code paths take fast routes:
         *   - ``record.update`` skips the mutex
         *   - ``record._update`` skips preprocessor awaits + onchange RPC
         *   - ``record.checkValidity`` skips ``_askChanges()``
         *   - ``record_save.save`` chooses the sendBeacon path
         *   - ``dynamic_list._askChanges`` skips ``editedRecord.checkValidity``
         *
         * The coordinator's ``run(fn)`` wraps entry in a try/finally
         * so the flag never leaks past the urgent save's lifetime even
         * if the inner work throws.  See
         * ``urgent_save_coordinator.js`` for the full rationale.
         *
         * @type {UrgentSaveCoordinator}
         */
        this.urgentSave = new UrgentSaveCoordinator(this.bus);
        /** @type {(() => void) | null} */
        this._closeUrgentSaveNotification = null;

        /**
         * In-flight *compound* updates: multi-step record mutations a field
         * widget drives across more than one ``mutex`` section, awaiting
         * something (an RPC, a variant lookup) in between. The mutex goes idle
         * in every one of those gaps, so ``mutex.getUnlockedDef()`` cannot see
         * them and {@link _askChanges} would call the model settled mid-cascade
         * — handing ``leaveEditMode`` / ``save`` / ``load`` a half-applied
         * record whose required fields the pending step has yet to write.
         * Widgets scope one with {@link trackCompoundUpdate}.
         *
         * @type {Set<Promise<unknown>>}
         */
        this._compoundUpdates = new Set();
    }

    exportState() {
        const config = { ...toRaw(this.config) };
        delete config.currentGroups;
        return {
            config,
            specialDataCaches: this.specialDataCaches,
        };
    }

    /**
     * @override
     * @type {Model["hasData"]}
     */
    hasData() {
        return this.root.hasData;
    }

    /**
     * Multi-edit dispatch: a selected record whose changes are committed
     * while ``multiEdit`` is enabled routes them through the model, which
     * forwards to the root list's multi-save — records must not reach into a
     * DynamicList subclass's protected state themselves.
     *
     * NB: this must stay a prototype method called through the record's own
     * reference chain (``record.model.multiEditDispatch(...)``): datapoints
     * are reactive proxies (SignalStore), and ``_multiSave`` compares record
     * identities (``editedRecord`` vs ``this.selection`` /
     * ``this._recordToDiscard``), which only match within a single reactive
     * domain. A closure capturing a list at construction time would run in
     * the base domain and break those comparisons.
     *
     * @param {import("./record").RelationalRecord} record
     * @param {Object} changes
     * @returns {Promise<any>}
     */
    multiEditDispatch(record, changes) {
        return this.root._multiSave(record, changes);
    }

    /**
     * @override
     * @type {Model["load"]}
     */
    async load(params = {}) {
        modelLog("load", this.config.resModel, params);
        if (this.orm.isSample && this.initialSampleGroups?.length) {
            this.orm.setGroups(this.initialSampleGroups);
        }
        const config = this._getNextConfig(this.config, params);
        if (!this.isReady) {
            this.root = this._createEmptyRoot(config);
            this.config = config;
        }
        this.hooks.lifecycle.onWillLoadRoot(config);
        const rootLoadDef = new Deferred();
        const cache = this._getCacheParams(config, rootLoadDef);
        // Debug-gated, like the identical instrumentation in
        // ``list_renderer.js``: nothing clears marks/measures anywhere in web,
        // so an ungated pair per load accumulated in the performance timeline
        // for the life of the tab and polluted any user-recorded profile.
        const profiling = Boolean(odoo.debug);
        if (profiling) {
            performance.mark("model:loadData:start");
        }
        const data = await this.keepLast.add(this._loadData(config, cache));
        if (profiling) {
            performance.measure("model:loadData", "model:loadData:start");
        }
        this.root = this._createRoot(config, data);
        rootLoadDef.resolve({ root: this.root, loadId: config.loadId });
        this.config = config;
        if (!this.isReady) {
            this.isReady = true;
        }
        await this.hooks.lifecycle.onRootLoaded(this.root);
    }

    /**
     * A group-by axis can name a property (``properties_field.property_name``)
     * that ``config.fields`` does not carry; fetch its definition and register
     * it as a synthetic field.
     *
     * A property dropped from its definition record still answers the
     * read_group — the stored values are still there — but
     * ``get_property_definition`` then returns an EMPTY definition, and a model
     * overriding it may return nothing at all. Both register a ``char``
     * placeholder rather than clearing the axis: the read_group has already run
     * on it, and every consumer downstream (``postprocessReadGroup``,
     * ``computeNextConfig``, ``_createEmptyRoot``, ``_loadData``) dereferences
     * ``groupBy`` as an array, so the previous ``config.groupBy = null`` turned
     * a missing label into a TypeError on the very next statement. Giving the
     * placeholder a ``type`` matters too: without one it falls through every
     * ``switch`` in the group-value helpers, silently skipping date/relational
     * handling instead of rendering a plain label.
     *
     * @param {RelationalModelConfig} config
     * @param {string} propertyFullName
     */
    async _getPropertyDefinition(config, propertyFullName) {
        const definition = await this.orm.call(
            config.resModel,
            "get_property_definition",
            [propertyFullName],
            { context: config.context },
        );
        config.fields[propertyFullName] = {
            ...(definition?.type ? definition : { type: "char" }),
            propertyName: definition?.name,
            name: propertyFullName,
            relatedPropertyField: {
                fieldName: propertyFullName.split(".")[0],
            },
            relation: definition?.comodel,
        };
        invalidateAggregateSpecs(config.fields);
    }

    /**
     * Scope a multi-step record mutation as one unit {@link _askChanges} waits
     * on, for widgets whose write cannot be expressed as a single mutex
     * section (a variant lookup between two writes, say).
     *
     * Call it *synchronously* at the point the user's edit is applied — never
     * from a render side effect. A barrier that only opens once the first
     * step's re-render has landed still leaves unguarded exactly the gap it
     * exists to close.
     *
     * @template T
     * @param {() => Promise<T>} fn
     * @returns {Promise<T>}
     */
    trackCompoundUpdate(fn) {
        const prom = Promise.resolve().then(fn);
        this._compoundUpdates.add(prom);
        const forget = () => this._compoundUpdates.delete(prom);
        prom.then(forget, forget);
        return prom;
    }

    async _askChanges() {
        // Settle in rounds: flushing an input can open a compound update, and a
        // compound update's next step re-takes the mutex. The model is settled
        // only once a whole round finds nothing left in flight. Each round
        // awaits the units it snapshotted, so a cascade of depth N drains in N
        // rounds; rounds cannot repeat forever unless a widget is looping.
        while (true) {
            const proms = [];
            this.bus.trigger(ModelEvent.NEED_LOCAL_CHANGES, { proms });
            // Only *completion* is the barrier's business: a failed cascade has
            // already reported itself, and rejecting here would fail the save
            // or the leave-edit-mode that merely waited behind it.
            const compound = [...this._compoundUpdates].map((p) => p.catch(() => {}));
            await Promise.all([...proms, ...compound, this.mutex.getUnlockedDef()]);
            if (!this._compoundUpdates.size) {
                return;
            }
        }
    }

    /**
     * Creates a root datapoint without data. Supported root types are DynamicRecordList and
     * DynamicGroupList.
     *
     * @param {RelationalModelConfig} config
     * @returns {DataPoint | undefined}
     */
    _createEmptyRoot(config) {
        if (!config.isMonoRecord) {
            if (config.groupBy.length) {
                return this._createRoot(config, { groups: [], length: 0 });
            }
            return this._createRoot(config, { records: [], length: 0 });
        }
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {Record<string, unknown>} data
     * @returns {any}
     */
    _createRoot(config, data) {
        if (config.isMonoRecord) {
            return new this.Class.Record(this, config, data);
        }
        if (config.groupBy.length) {
            return new this.Class.DynamicGroupList(this, config, data);
        }
        return new this.Class.DynamicRecordList(this, config, data);
    }

    _getCacheParams(config, rootLoadDef) {
        if (!this.withCache) {
            return;
        }
        const currentResId = config.resId;
        if (
            !this.isReady ||
            (config.isMonoRecord &&
                (this.root.config.resId !== config.resId || !config.resId))
        ) {
            return {
                type: "disk",
                update: "always",
                callback: async (result, hasChanged) => {
                    if (!hasChanged) {
                        return;
                    }
                    const { root, loadId } = await rootLoadDef;
                    if (
                        root.config.isMonoRecord &&
                        currentResId !== root.config.resId
                    ) {
                        return;
                    }
                    if (root.id !== this.root.id) {
                        if (this.useSampleModel) {
                            this.useSampleModel = false;
                            if (this.root.config.groupBy.length) {
                                delete this.root.config.currentGroups;
                                result = await this._postprocessReadGroup(
                                    this.root.config,
                                    result,
                                );
                            }
                            this.root._setData(result);
                        }
                        return;
                    }
                    if (loadId !== this.root.config.loadId) {
                        return;
                    }
                    if (root.config.isMonoRecord) {
                        if (!root.config.resId) {
                            return root._setData(result.value, {
                                keepChanges: true,
                            });
                        }
                        if (!result.length) {
                            throw new FetchRecordError([root.config.resId]);
                        }
                        return root._setData(result[0], { keepChanges: true });
                    }

                    if (
                        root.records.some((r) => r.isInEdition || r.dirty || r.selected)
                    ) {
                        return;
                    }
                    if (root.config.groupBy.length) {
                        delete this.root.config.currentGroups;
                        result = await this._postprocessReadGroup(root.config, result);
                    }
                    root._setData(result);
                },
            };
        }
    }

    /**
     * @param {RelationalModelConfig} currentConfig
     * @param {Partial<SearchParams>} params
     * @returns {RelationalModelConfig}
     */
    _getNextConfig(currentConfig, params) {
        return computeNextConfig(currentConfig, params, {
            maxGroupByDepth: this.maxGroupByDepth,
            defaultOrderBy: this.defaultOrderBy,
            hasRoot: Boolean(this.root),
        });
    }

    /**
     *
     * @param {RelationalModelConfig} config
     * @param {Object} [cache]
     */
    async _loadData(config, cache) {
        config.loadId = getId("load");
        if (config.isMonoRecord) {
            const evalContext = getBasicEvalContext(config);
            if (!config.resId) {
                return this._loadNewRecord(config, { evalContext, cache });
            }
            const records = await this._loadRecords(config, evalContext, cache);
            return records[0];
        }
        if (config.resIds) {
            const resIds = config.resIds.slice(
                config.offset,
                config.offset + config.limit,
            );
            return this._loadRecords({ ...config, resIds }, config.context, cache);
        }
        if (config.groupBy.length) {
            return this._loadGroupedList(config, cache);
        }
        Object.assign(config, {
            limit: config.limit || this.initialLimit,
            countLimit:
                "countLimit" in config ? config.countLimit : this.initialCountLimit,
            offset: config.offset || 0,
        });
        if (config.countLimit !== Number.MAX_SAFE_INTEGER) {
            config.countLimit = Math.max(
                config.countLimit,
                config.offset + config.limit,
            );
        }
        const { records, length } = await this._loadUngroupedList(config, cache);
        if (config.offset && !records.length) {
            config.offset = 0;
            return this._loadData(config, cache);
        }
        return { records, length };
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {Object} [cache]
     */
    async _loadGroupedList(config, cache) {
        config.offset = config.offset || 0;
        config.limit = config.limit || this.initialGroupsLimit;
        if (!config.limit) {
            config.limit = config.openGroupsByDefault
                ? this.Class.DEFAULT_OPEN_GROUP_LIMIT
                : this.Class.DEFAULT_GROUP_LIMIT;
        }
        config.groups = config.groups || {};

        const response = await this._webReadGroup(config, cache);
        return this._postprocessReadGroup(config, response);
    }

    async _postprocessReadGroup(config, response) {
        return postprocessReadGroup(config, response, {
            getPropertyDefinition: (cfg, propertyFullName) =>
                this._getPropertyDefinition(cfg, propertyFullName),
            groupByInfo: this.groupByInfo,
            initialLimit: this.initialLimit,
            initialGroupsLimit: this.initialGroupsLimit,
            defaultGroupLimit: this.Class.DEFAULT_GROUP_LIMIT,
        });
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {OnChangeParams} [params={}]
     * @returns {Promise<Record<string, any>>}
     */
    async _loadNewRecord(config, params = {}) {
        return this._onchange(config, params);
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {Context} evalContext
     * @param {Object} [cache]
     */
    async _loadRecords(config, evalContext = config.context, cache) {
        const { resModel, activeFields, fields, context } = config;
        const resIds = config.resId ? [config.resId] : config.resIds;
        if (!resIds.length) {
            return [];
        }
        const fieldSpec = getFieldsSpec(activeFields, fields, evalContext);
        if (Object.keys(fieldSpec).length > 0) {
            const kwargs = {
                context: { bin_size: true, ...context },
                specification: fieldSpec,
            };
            const orm = cache ? this.orm.cache(cache) : this.orm;
            const records = await orm.webRead(resModel, resIds, kwargs);
            if (!records.length) {
                throw new FetchRecordError(resIds);
            }

            return records;
        } else {
            return resIds.map((resId) => ({ id: resId }));
        }
    }

    /**
     * Load records from the server for an ungrouped list. Return the result
     * of unity read RPC.
     *
     * @param {RelationalModelConfig} config
     * @param {Object} [cache]
     */
    async _loadUngroupedList(config, cache) {
        const orderBy = config.orderBy.filter((o) => o.name !== "__count");
        let order = orderByToString(orderBy);
        if (config.isGroupList && order && !orderBy.some((o) => o.name === "id")) {
            order += ", id ASC";
        }
        const kwargs = {
            specification: getFieldsSpec(
                config.activeFields,
                config.fields,
                config.context,
            ),
            offset: config.offset,
            order,
            limit: config.limit,
            context: { bin_size: true, ...config.context },
            count_limit:
                config.countLimit !== Number.MAX_SAFE_INTEGER
                    ? config.countLimit + 1
                    : undefined,
        };
        const orm = cache ? this.orm.cache(cache) : this.orm;
        return orm.webSearchRead(config.resModel, config.domain, kwargs);
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {OnChangeParams} params
     * @returns {Promise<Record<string, unknown>>}
     */
    async _onchange(
        config,
        { changes = {}, fieldNames = [], evalContext = config.context, onError, cache },
    ) {
        if (!this.isAlive()) {
            // Committing a pending edit (blur / NEED_LOCAL_CHANGES) races the
            // teardown that provoked it: escape out of a FormViewDialog flushes
            // the focused input, and the onchange it triggers lands after the
            // dialog is gone. The RPC then travels through the destroyed
            // component's service proxy and rejects with "Component is
            // destroyed" inside a promise nobody is left to await. No onchange
            // values can matter to a view that no longer exists, so answer the
            // no-op the callers already understand.
            return {};
        }
        const { fields, activeFields, resModel, resId } = config;
        let context = config.context;
        if (fieldNames.length === 1) {
            const fieldContext = config.activeFields[fieldNames[0]].context;
            context = makeContext([context, fieldContext], evalContext);
        }
        const spec = getFieldsSpec(activeFields, fields, evalContext, {
            withInvisible: true,
        });
        const args = [resId ? [resId] : [], changes, fieldNames, spec];
        let response;
        try {
            const orm = cache ? this.orm.cache(cache) : this.orm;
            response = await orm.call(resModel, "onchange", args, { context });
        } catch (e) {
            if (onError) {
                return void onError(e);
            }
            throw e;
        }
        if (response.warning) {
            Promise.resolve(
                this.hooks.lifecycle.onWillDisplayOnchangeWarning(response.warning),
            )
                .then(() => {
                    this.hooks.ui.onDisplayOnchangeWarning(response.warning);
                })
                .catch((error) => console.error(error));
        }
        return response.value;
    }

    /**
     * Synchronously applies ``patch`` to ``config`` (no reload, no promise).
     *
     * SYNCHRONY IS LOAD-BEARING: 20+ call sites (mode switches, resId
     * commits after save, limit/offset bookkeeping, group fold state, …)
     * rely on the patched config being visible in the very next statement,
     * without awaiting. This method MUST NOT become async and MUST NOT
     * await anything — that's the whole reason it is split from
     * ``_reloadWithConfig``, whose historical ``{ reload: false }`` mode
     * only happened to be synchronously visible because no ``await``
     * preceded the assign. Pinned by a unit test
     * (relational_model_config.test.js).
     *
     * @param {RelationalModelConfig} config
     * @param {Partial<RelationalModelConfig>} patch
     */
    _patchConfig(config, patch) {
        const tmpConfig = { ...config, ...patch };
        markRaw(tmpConfig.activeFields);
        markRaw(tmpConfig.fields);
        Object.assign(config, tmpConfig);
    }

    /**
     * Asynchronously applies ``patch`` to ``config`` and reloads the
     * corresponding data. The data is loaded against a candidate config and
     * only committed into ``config`` (via ``_patchConfig``) once the load
     * has succeeded, so a rejected load leaves ``config`` untouched.
     *
     * For a pure config patch with no reload, use the synchronous
     * ``_patchConfig`` instead.
     *
     * @param {RelationalModelConfig} config
     * @param {Partial<RelationalModelConfig>} patch
     * @param {{
     *  commit?: (data: Record<string, unknown>) => unknown;
     * }} [options]
     */
    async _reloadWithConfig(config, patch, { commit } = {}) {
        const tmpConfig = { ...config, ...patch };
        if (tmpConfig.groups) {
            tmpConfig.groups = cloneGroupTree(tmpConfig.groups);
        }
        markRaw(tmpConfig.activeFields);
        markRaw(tmpConfig.fields);
        if (tmpConfig.isRoot) {
            this.hooks.lifecycle.onWillLoadRoot(tmpConfig);
        }
        const data = await this._loadData(tmpConfig);
        this._patchConfig(config, tmpConfig);
        if (data && commit) {
            commit(data);
        }
        if (config.isRoot) {
            await this.hooks.lifecycle.onRootLoaded(this.root);
        }
    }

    /**
     *
     * @param {RelationalModelConfig} config
     * @returns {Promise<number>}
     */
    async _updateCount(config) {
        const count = await this.countKeepLast.add(
            this.orm.searchCount(config.resModel, config.domain, {
                context: config.context,
            }),
        );
        config.countLimit = Number.MAX_SAFE_INTEGER;
        return count;
    }

    /**
     * When grouped by a many2many field, the same record may appear in several
     * groups; propagate a reloaded record's values to all its other occurrences.
     *
     * @param {RelationalRecord} reloadedRecord
     * @param {Record<string, unknown>} serverValues
     */
    _updateSimilarRecords(reloadedRecord, serverValues) {
        if (this.config.isMonoRecord || !this.config.groupBy.length) {
            return;
        }
        for (const record of this.root.records) {
            if (record === reloadedRecord) {
                continue;
            }
            if (record.resId === reloadedRecord.resId) {
                record._applyValues(serverValues);
            }
        }
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {Object} cache
     */
    async _webReadGroup(config, cache) {
        const { aggregates, params } = buildWebReadGroupParams(config, {
            groupByInfo: this.groupByInfo,
            initialLimit: this.initialLimit,
        });
        const orm = cache ? this.orm.cache(cache) : this.orm;
        const result = await orm.webReadGroup(
            config.resModel,
            config.domain,
            config.groupBy,
            aggregates,
            params,
        );
        if (this.canUseSampleModel && !this.initialSampleGroups) {
            this.initialSampleGroups = deepCopy(
                result.groups.map((group) =>
                    "__records" in group ? { ...group, __records: [] } : group,
                ),
            );
        }
        return result;
    }
}
