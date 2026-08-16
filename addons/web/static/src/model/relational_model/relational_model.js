// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/relational_model */

import { markRaw, toRaw } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { ModelEvent } from "@web/core/events";
import { modelLog } from "@web/core/utils/asset_log";
import { deepCopy } from "@web/core/utils/collections/objects";
import {
    Deferred,
    KeepLast,
    Mutex,
    SupersededError,
} from "@web/core/utils/concurrency";
import { orderByToString } from "@web/core/utils/order_by";
import { Model } from "@web/model/model";

import { cloneGroupTree, computeNextConfig } from "./config_transitions.js";
import { DynamicGroupList } from "./dynamic_group_list.js";
import { DynamicRecordList } from "./dynamic_record_list.js";
import { FetchRecordError } from "./errors.js";
import { getId, getSpecEvalContext } from "./field_context.js";
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
 *  canUseSampleModel?: boolean;
 *  isAlive?: () => boolean;
 * }} RelationalModelParams
 * @typedef {{
 *  config: RelationalModelConfig;
 *  specialDataCaches: import("./special_data_cache.js").SpecialDataCache;
 * }} RelationalModelState
 */

/**
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
 * @typedef {{
 *  onDisplayOnchangeWarning: (warning: {type: string, title: string, message: string, className?: string, sticky?: boolean}) => void;
 *  onDisplayInvalidFields: () => (() => void);
 *  onDisplayUrgentSave: (message: string) => (() => void);
 *  onDisplayPropertyWarning: (message: string) => void;
 *  onDisplayArchiveAction: (action: Object, reload: () => Promise<any>) => any;
 *  onConfirmArchive: (archiveFn: Function, dialogProps?: Object) => void;
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
    onConfirmArchive: (archiveFn) => archiveFn(),
    onConfirmDuplicate: (resIds, copyFn) => copyFn(resIds),
    onDisplayLimitNotification: () => {},
});

const ASK_CHANGES_MAX_ROUNDS = 100;

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

    // No class-field declarations: `Model`'s constructor calls `setup()` (it
    // says so at model.js:259), and a subclass field initialiser runs after
    // `super()` returns, so one would blank what `setup()` assigned.

    /** @returns {typeof RelationalModel} */
    get Class() {
        return /** @type {typeof RelationalModel} */ (this.constructor);
    }

    /**
     * @param {RelationalModelParams} params
     * @param {Object} _services
     */
    setup(params, _services) {
        // `rejectSuperseded` so a dropped load settles its caller instead of
        // leaving the promise pending forever; `load()` catches
        // `SupersededError` and resolves, matching the callers that
        // `await model.load()`. Same contract calendar, graph and pivot already
        // use.
        this.keepLast = markRaw(new KeepLast({ rejectSuperseded: true }));
        this.countKeepLast = markRaw(new KeepLast({ rejectSuperseded: true }));
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
        /** @type {Map<string, Set<Function>>} */
        this._lifecycleListeners = new Map();
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
         * @type {UrgentSaveCoordinator}
         */
        this.urgentSave = new UrgentSaveCoordinator(this.bus);
        /** @type {(() => void) | null} */
        this._closeUrgentSaveNotification = null;
        /**
         * @type {Deferred | null}
         */
        this._rootLoadDef = null;

        /**
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
     * Shows the "changes too large to save automatically" notification, keeping
     * its disposer. The model owns that disposer because the notification
     * outlives the save that raised it: a later save, a discard, or leaving edit
     * mode all have to take it down, and none of them can be handed the closure.
     *
     * @param {ReturnType<typeof import("@web/core/translation")._t>} message
     * @returns {void}
     */
    displayUrgentSaveNotification(message) {
        this._closeUrgentSaveNotification = this.hooks.ui.onDisplayUrgentSave(message);
    }

    /**
     * @returns {void}
     */
    closeUrgentSaveNotification() {
        if (this._closeUrgentSaveNotification) {
            this._closeUrgentSaveNotification();
        }
    }

    /**
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
        this._notifyLifecycle("onWillLoadRoot", config);
        const rootLoadDef = new Deferred();
        this._retireRootLoadDef();
        this._rootLoadDef = rootLoadDef;
        const cache = this._getCacheParams(config, rootLoadDef);
        const profiling = Boolean(odoo.debug);
        if (profiling) {
            performance.mark("model:loadData:start");
        }
        let data;
        // Cancels the RPCs this load issues if a newer one supersedes it. The
        // controller reaches them through `_scopedOrm`; `KeepLast` runs the
        // abort at the moment it stops caring about the result.
        const loadAbort = new AbortController();
        try {
            data = await this.keepLast.add(
                this._loadData(config, cache, loadAbort.signal),
                { abort: () => loadAbort.abort() },
            );
        } catch (error) {
            if (error instanceof SupersededError) {
                // A newer load owns `_rootLoadDef` now -- retiring here would
                // retire *its* deferred, not ours. Drop this load silently and
                // resolve, which is what the caller means by "a newer load took
                // over".
                return;
            }
            this._retireRootLoadDef();
            throw error;
        }
        if (profiling) {
            performance.measure("model:loadData", "model:loadData:start");
        }
        this.root = this._createRoot(config, data);
        rootLoadDef.resolve({ root: this.root, loadId: config.loadId });
        if (this._rootLoadDef === rootLoadDef) {
            this._rootLoadDef = null;
        }
        this.config = config;
        if (!this.isReady) {
            this.isReady = true;
        }
        await this.hooks.lifecycle.onRootLoaded(this.root);
        const notified = this._notifyLifecycle("onRootLoaded", this.root);
        if (notified) {
            await notified;
        }
    }

    /**
     * Subscribes an ADDITIONAL listener to a lifecycle hook, run after the hook
     * itself. Unlike assigning `hooks.lifecycle.<name>`, which is a single slot
     * and silently replaces whatever was there, subscriptions compose: several
     * independent features can observe the same hook, and unsubscribing one
     * cannot resurrect a stale version of another.
     *
     * @param {string} name a key of `hooks.lifecycle`
     * @param {Function} listener
     * @returns {() => void} unsubscribe
     */
    subscribeLifecycle(name, listener) {
        let listeners = this._lifecycleListeners.get(name);
        if (!listeners) {
            listeners = new Set();
            this._lifecycleListeners.set(name, listeners);
        }
        listeners.add(listener);
        return () => listeners.delete(listener);
    }

    /**
     * Returns a promise ONLY when there is something to run. An `async` method
     * would resolve to a promise even with no listeners, and awaiting it would
     * insert a microtask tick into the load path on every call — enough to
     * reorder the render/response interleaving callers observe.
     *
     * @param {string} name
     * @param {...any} args
     * @returns {Promise<void> | undefined}
     */
    _notifyLifecycle(name, ...args) {
        const listeners = this._lifecycleListeners.get(name);
        if (!listeners?.size) {
            return;
        }
        return this._runLifecycleListeners([...listeners], args);
    }

    /**
     * @param {Function[]} listeners
     * @param {any[]} args
     * @returns {Promise<void>}
     */
    async _runLifecycleListeners(listeners, args) {
        for (const listener of listeners) {
            await listener(...args);
        }
    }

    /**
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

    /**
     * A reload replaces every datapoint, so anything a widget is still holding
     * locally is lost with them. Draining `_askChanges()` first is what makes
     * "type in a cell, then change the search facet" keep the typed value.
     *
     * Guarded on `mutex.locked` because that is the only state in which there
     * can be an in-flight update to settle; asking unconditionally would add a
     * bus round trip and a microtask to every idle reload.
     *
     * Returns the pending settle, or nothing at all when the mutex is free --
     * the caller must be able to skip awaiting in the idle case. See the note
     * on `Model#settleBeforeReload`.
     *
     * @override
     * @returns {Promise<void> | void}
     */
    settleBeforeReload() {
        if (this.mutex.locked) {
            return this._askChanges();
        }
    }

    async _askChanges() {
        for (let round = 0; round < ASK_CHANGES_MAX_ROUNDS; round++) {
            const proms = [];
            this.bus.trigger(ModelEvent.NEED_LOCAL_CHANGES, { proms });
            const compound = [...this._compoundUpdates].map((p) => p.catch(() => {}));
            await Promise.all([...proms, ...compound, this.mutex.getUnlockedDef()]);
            if (!this._compoundUpdates.size) {
                return;
            }
        }
        console.warn(
            `RelationalModel._askChanges: local changes did not settle after ` +
                `${ASK_CHANGES_MAX_ROUNDS} rounds (resModel: ${this.config.resModel}); ` +
                `${this._compoundUpdates.size} compound update(s) still in flight. ` +
                `A field widget is very likely re-opening one from a render side ` +
                `effect — see trackCompoundUpdate(). Proceeding unsettled.`,
        );
    }

    /**
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

    _retireRootLoadDef() {
        if (this._rootLoadDef) {
            this._rootLoadDef.resolve(null);
            this._rootLoadDef = null;
        }
    }

    /**
     * The ORM this load should talk to: cache proxy when the load is cacheable,
     * signal proxy when it is cancellable, both when it is both.
     *
     * Replaces four copies of `cache ? this.orm.cache(cache) : this.orm`, which
     * is where the signal has to be applied -- every RPC the load path issues
     * goes through one of them.
     *
     * @param {Object} [cache]
     * @param {AbortSignal} [signal]
     * @returns {import("@web/core/network/orm_service").ORM}
     */
    _scopedOrm(cache, signal) {
        let orm = this.orm;
        if (cache) {
            orm = orm.cache(cache);
        }
        if (signal) {
            orm = orm.withSignal(signal);
        }
        return orm;
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
                callback: (result, hasChanged) =>
                    this._applyBackgroundRefresh(result, hasChanged, {
                        rootLoadDef,
                        currentResId,
                    }),
            };
        }
    }

    /**
     * Stale-while-revalidate: apply a disk-cache background refresh to the live
     * root, but only when doing so cannot corrupt what the user is looking at
     * or editing. This is the subtlest guard in the load path — every early
     * return below is a distinct "do not touch the root" condition.
     *
     * @param {any} result   the freshly revalidated payload
     * @param {boolean} hasChanged   whether it differs from what was served
     * @param {{ rootLoadDef: Promise<any>, currentResId: any }} ctx
     */
    async _applyBackgroundRefresh(result, hasChanged, { rootLoadDef, currentResId }) {
        // The served copy was already current — nothing to reconcile.
        if (!hasChanged) {
            return;
        }
        // The root's own load never resolved, so there is no root to refresh.
        const loaded = await rootLoadDef;
        if (!loaded) {
            return;
        }
        const { root, loadId } = loaded;
        // The record navigated away between serve and revalidate.
        if (root.config.isMonoRecord && currentResId !== root.config.resId) {
            return;
        }
        // A different root is mounted now; only feed it if it is sample data
        // still waiting for its first real payload.
        if (root.id !== this.root.id) {
            if (this.useSampleModel) {
                this.useSampleModel = false;
                if (this.root.config.groupBy.length) {
                    delete this.root.config.currentGroups;
                    result = await this._postprocessReadGroup(this.root.config, result);
                }
                this.root._setData(result);
            }
            return;
        }
        // A newer load of this same root has already superseded us.
        if (loadId !== this.root.config.loadId) {
            return;
        }
        if (root.config.isMonoRecord) {
            if (!root.config.resId) {
                return root._setData(result.value, { keepChanges: true });
            }
            if (!result.length) {
                throw new FetchRecordError([root.config.resId]);
            }
            return root._setData(result[0], { keepChanges: true });
        }
        // A visible record is being edited or is selected — refreshing would
        // discard the user's in-flight work.
        if (
            root.records.some((r) => r.isInEdition || r.hasPendingChanges || r.selected)
        ) {
            return;
        }
        if (root.config.groupBy.length) {
            delete this.root.config.currentGroups;
            result = await this._postprocessReadGroup(root.config, result);
        }
        root._setData(result);
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
     * @param {RelationalModelConfig} config
     * @param {Object} [cache]
     * @param {AbortSignal} [signal] cancels this load's RPCs when a newer load supersedes it
     */
    async _loadData(config, cache, signal) {
        config.loadId = getId("load");
        if (config.isMonoRecord) {
            const evalContext = getSpecEvalContext(config);
            if (!config.resId) {
                return this._loadNewRecord(config, { evalContext, cache, signal });
            }
            const records = await this._loadRecords(config, evalContext, cache, signal);
            return records[0];
        }
        if (config.resIds) {
            // Defaults first: this branch used to slice with a `limit` nothing
            // had filled in yet, so `offset + undefined` was NaN and the slice
            // silently produced an empty list instead of the first page.
            Object.assign(config, {
                limit: config.limit || this.initialLimit,
                offset: config.offset || 0,
            });
            const resIds = config.resIds.slice(
                config.offset,
                config.offset + config.limit,
            );
            const records = await this._loadRecords(
                { ...config, resIds },
                getSpecEvalContext(config),
                cache,
            );
            return { records, length: config.resIds.length };
        }
        if (config.groupBy.length) {
            return this.loadGroupedList(config, cache, signal);
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
        const { records, length } = await this._loadUngroupedList(
            config,
            cache,
            signal,
        );
        if (config.offset && !records.length) {
            config.offset = 0;
            return this._loadData(config, cache);
        }
        return { records, length };
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {Object} [cache]
     * @param {AbortSignal} [signal] cancels this load's RPCs when a newer load supersedes it
     */
    async loadGroupedList(config, cache, signal) {
        config.offset = config.offset || 0;
        config.limit = config.limit || this.initialGroupsLimit;
        if (!config.limit) {
            config.limit = config.openGroupsByDefault
                ? this.Class.DEFAULT_OPEN_GROUP_LIMIT
                : this.Class.DEFAULT_GROUP_LIMIT;
        }
        config.groups = config.groups || {};

        const response = await this.webReadGroup(config, cache, signal);
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
     * The default is what every in-repo caller passes explicitly. Leaving it
     * required made an omission evaluate every field spec against `undefined`
     * instead of failing — a silent contract for out-of-repo subclasses.
     *
     * @param {RelationalModelConfig} config
     * @param {Context} [evalContext]
     * @param {Object} [cache]
     * @param {AbortSignal} [signal] cancels this load's RPCs when a newer load supersedes it
     */
    async _loadRecords(
        config,
        evalContext = getSpecEvalContext(config),
        cache,
        signal,
    ) {
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
            const orm = this._scopedOrm(cache, signal);
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
     * @param {RelationalModelConfig} config
     * @param {Object} [cache]
     * @param {AbortSignal} [signal] cancels this load's RPCs when a newer load supersedes it
     * @returns {Promise<{ records: any[]; length: number }>}
     */
    async _loadUngroupedList(config, cache, signal) {
        const orderBy = config.orderBy.filter((o) => o.name !== "__count");
        let order = orderByToString(orderBy);
        if (config.isGroupList && order && !orderBy.some((o) => o.name === "id")) {
            order += ", id ASC";
        }
        const kwargs = {
            specification: getFieldsSpec(
                config.activeFields,
                config.fields,
                getSpecEvalContext(config),
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
        const orm = this._scopedOrm(cache, signal);
        return orm.webSearchRead(config.resModel, config.domain, kwargs);
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {OnChangeParams} params
     * @returns {Promise<Record<string, unknown>>}
     */
    async _onchange(
        config,
        {
            changes = {},
            fieldNames = [],
            evalContext = getSpecEvalContext(config),
            onError,
            cache,
            signal,
        },
    ) {
        if (!this.isAlive()) {
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
            const orm = this._scopedOrm(cache, signal);
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
            this._notifyLifecycle("onWillLoadRoot", tmpConfig);
        }
        const data = await this._loadData(tmpConfig);
        this._patchConfig(config, tmpConfig);
        if (data && commit) {
            commit(data);
        }
        if (config.isRoot) {
            await this.hooks.lifecycle.onRootLoaded(this.root);
            const notified = this._notifyLifecycle("onRootLoaded", this.root);
            if (notified) {
                await notified;
            }
        }
    }

    /**
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
     * @param {AbortSignal} [signal] cancels this load's RPCs when a newer load supersedes it
     * @returns {Promise<{ groups: any[]; length: number }>}
     */
    async webReadGroup(config, cache, signal) {
        const { aggregates, params } = buildWebReadGroupParams(config, {
            groupByInfo: this.groupByInfo,
            initialLimit: this.initialLimit,
        });
        const orm = this._scopedOrm(cache, signal);
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
