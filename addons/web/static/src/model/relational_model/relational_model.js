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

import { computeNextConfig } from "./config_transitions.js";
import { DynamicGroupList } from "./dynamic_group_list.js";
import { DynamicRecordList } from "./dynamic_record_list.js";
import { FetchRecordError } from "./errors.js";
import { RelationalModelLoadCoordinator } from "./load_coordinator.js";
import { getBasicEvalContext, getId } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";
import { Group } from "./group.js";
import { postprocessReadGroup } from "./group_postprocessor.js";
import { buildWebReadGroupParams } from "./read_group_builder.js";
import { RelationalRecord } from "./record.js";
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
 *  specialDataCaches: Record<string, unknown>;
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

// The RESULT_SET_REMOVING_METHODS set and the RPC:RESPONSE → CLEAR-CACHES
// bridge that used to live here moved to
// ``@web/services/result_set_cache_invalidator_service`` so the wiring is
// owned by env lifecycle (one listener per page in prod, one per test in
// Hoot) instead of being a module-load side effect. See that file for the
// full rationale.

export class RelationalModel extends Model {
    // Only ``orm`` is needed by the model itself. Earlier revisions injected
    // ``action`` / ``dialog`` / ``notification`` for in-model UI side effects;
    // those callsites now flow through controller-supplied hooks
    // (``makeModelUIHooks`` in ``views/view_utils``), so the model layer no
    // longer reaches into the UI service registry. Verified 2026-05-21: zero
    // ``model.{action,dialog,notification}`` accesses across core, enterprise,
    // and agromarin.
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
        this.mutex = markRaw(new Mutex());

        // Observable load-lifecycle state machine. Mirrors
        // ``FormSaveCoordinator`` for the save axis: provides a
        // ``status: idle | loading | error`` surface plus
        // ``lastError`` for diagnostics. Wired through ``load()`` for
        // status tracking; does NOT replace ``keepLast`` (cancellation
        // semantics), ``mutex`` (per-record save/discard
        // serialization), or ``urgentSave`` (cross-cutting mode
        // coordinator, see ``urgent_save_coordinator.js``) — those
        // serve orthogonal concerns. See ``load_coordinator.js`` for
        // the full scope rationale.
        this.loadCoordinator = new RelationalModelLoadCoordinator();

        /** @type {RelationalModelConfig} */
        this.config = {
            isMonoRecord: false,
            context: {},
            fieldsToAggregate: Object.keys(params.config.activeFields), // active fields by default
            ...params.config,
            isRoot: true,
        };

        this.hooks = {
            lifecycle: { ...DEFAULT_LIFECYCLE_HOOKS, ...params.hooks?.lifecycle },
            ui: { ...DEFAULT_UI_HOOKS, ...params.hooks?.ui },
        };

        this.initialLimit = params.limit || this.Class.DEFAULT_LIMIT;
        this.initialGroupsLimit = params.groupsLimit;
        this.initialCountLimit = params.countLimit || this.Class.DEFAULT_COUNT_LIMIT;
        this.defaultOrderBy = params.defaultOrderBy;
        this.maxGroupByDepth = params.maxGroupByDepth;
        this.groupByInfo = params.groupByInfo || {};
        this.multiEdit = params.multiEdit;
        this.activeIdsLimit = params.activeIdsLimit || Number.MAX_SAFE_INTEGER;
        this.specialDataCaches = markRaw(params.state?.specialDataCaches || {});
        this.useSendBeaconToSaveUrgently = params.useSendBeaconToSaveUrgently || false;
        this.withCache = this.Class.withCache && this.env.config?.cache;
        this.initialSampleGroups = undefined; // real groups to populate with sample records

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
    }

    /**
     * Backward-compat facade. Delegates to
     * ``urgentSave.run(fn)`` so existing callers in record.js keep
     * working through the same entry point.  New code should prefer
     * ``model.urgentSave.run(...)`` directly.
     *
     * @template T
     * @param {() => Promise<T>} fn
     * @returns {Promise<T>}
     */
    _withUrgentSaveScope(fn) {
        return this.urgentSave.run(fn);
    }

    // -------------------------------------------------------------------------
    // Public
    // -------------------------------------------------------------------------

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
            // We want the control panel to be displayed directly, without waiting for data to be
            // loaded, for instance to be able to interact with the search view. For that reason, we
            // create an empty root, without data, s.t. controllers can make the assumption that the
            // root is set when they are rendered. The root is replaced later on by the real root,
            // when data are loaded.
            this.root = this._createEmptyRoot(config);
            this.config = config;
        }
        this.hooks.lifecycle.onWillLoadRoot(config);
        const rootLoadDef = new Deferred();
        const cache = this._getCacheParams(config, rootLoadDef);
        performance.mark("model:loadData:start");
        // Route the actual data load through ``loadCoordinator.run`` so
        // ``loadCoordinator.status`` reflects the in-flight load and
        // observers (loading spinners, route guards) can react. The
        // ``keepLast.add`` cancellation wrapper still runs inside —
        // ``run`` doesn't replace it, it adds a status-narration layer
        // around it. A failed load rejects through ``run``'s
        // ``failed``-transition path; a stale rejection (superseded by
        // a newer ``keepLast.add``) lands on the epoch-bumped
        // coordinator and becomes a silent no-op.
        const data = await this.loadCoordinator.run(() =>
            this.keepLast.add(this._loadData(config, cache)),
        );
        performance.measure("model:loadData", "model:loadData:start");
        this.root = this._createRoot(config, data);
        rootLoadDef.resolve({ root: this.root, loadId: config.loadId });
        this.config = config;
        // Promote ``isReady`` in the same synchronous block as the real-
        // root + config writes so OWL's reactivity batches all three into
        // a single render.  Keeping the old ``this.isReady = true`` in
        // ``whenReady.then`` (model.js:83-86) instead would put the write
        // in a later microtask separated by the upcoming ``await
        // onRootLoaded(...)``, producing a third render visible to
        // ``onRendered`` step assertions on mount.  ``whenReady`` is still
        // resolved by the useModel/useModelWithSampleData wrapper after
        // ``load`` returns — consumers awaiting that promise continue to
        // work unchanged.
        if (!this.isReady) {
            this.isReady = true;
        }
        await this.hooks.lifecycle.onRootLoaded(this.root);
    }

    // -------------------------------------------------------------------------
    // Protected
    // -------------------------------------------------------------------------

    /**
     * If we group by default based on a property, the property might not be loaded in `fields`.
     *
     * @param {RelationalModelConfig} config
     * @param {string} propertyFullName
     */
    async _getPropertyDefinition(config, propertyFullName) {
        // dynamically load the property and add the definition in the fields attribute
        const result = await this.orm.call(
            config.resModel,
            "get_property_definition",
            [propertyFullName],
            { context: config.context },
        );
        if (!result) {
            // the property might have been removed
            config.groupBy = null;
        } else {
            result.propertyName = result.name;
            result.name = propertyFullName; // "xxxxx" -> "property.xxxxx"
            // needed for _applyChanges
            result.relatedPropertyField = {
                fieldName: propertyFullName.split(".")[0],
            };
            result.relation = result.comodel; // match name on field
            config.fields[propertyFullName] = result;
        }
    }

    async _askChanges() {
        const proms = [];
        this.bus.trigger(ModelEvent.NEED_LOCAL_CHANGES, { proms });
        await Promise.all([...proms, this.mutex.getUnlockedDef()]);
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
            !this.isReady || // first load of the model
            // monorecord, loading a different id, or creating a new record (onchange)
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
                    if (root.config.isMonoRecord && currentResId !== root.config.resId) {
                        // The record ID has been changed, likely because a new record was saved.
                        return;
                    }
                    if (root.id !== this.root.id) {
                        // The root id might have changed, either because:
                        //  1) the user already changed the domain and a second load has been done
                        //  2) there was no data, so we reloaded directly with the sample orm
                        // In the first case, there's nothing to do, we can ignore this update. We
                        // have to deal with the second case:
                        if (this.useSampleModel) {
                            // We displayed sample data from the cache, but the rpc returned records
                            // or groups => leave sample mode, forget previous groups and update
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
                        // Avoid updating if another load was already done (e.g. a sort in a list)
                        return;
                    }
                    if (root.config.isMonoRecord) {
                        if (!root.config.resId) {
                            // result is the response of the onchange rpc
                            return root._setData(result.value, {
                                keepChanges: true,
                            });
                        }
                        // result is the response of a web_read rpc
                        if (!result.length) {
                            // we read a record that no longer exists
                            throw new FetchRecordError([root.config.resId]);
                        }
                        return root._setData(result[0], { keepChanges: true });
                    }

                    // multi record case: either grouped or ungrouped
                    if (root.config.groupBy.length) {
                        // result is the response of a web_read_group rpc
                        // in case there're less groups, we don't want to keep displaying groups
                        // that are no longer there => forget previous groups
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
            // static list
            const resIds = config.resIds.slice(
                config.offset,
                config.offset + config.limit,
            );
            return this._loadRecords({ ...config, resIds });
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
        const kwargs = {
            specification: getFieldsSpec(
                config.activeFields,
                config.fields,
                config.context,
            ),
            offset: config.offset,
            order: orderByToString(orderBy),
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
            ).then(() => {
                this.hooks.ui.onDisplayOnchangeWarning(response.warning);
            });
        }
        return response.value;
    }

    /**
     * @param {RelationalModelConfig} config
     * @param {Partial<RelationalModelConfig>} patch
     * @param {{
     *  commit?: (data: Record<string, unknown>) => unknown;
     *  reload?: boolean;
     * }} [options]
     */
    async _updateConfig(config, patch, { reload = true, commit } = {}) {
        const tmpConfig = { ...config, ...patch };
        markRaw(tmpConfig.activeFields);
        markRaw(tmpConfig.fields);

        let data;
        if (reload) {
            if (tmpConfig.isRoot) {
                this.hooks.lifecycle.onWillLoadRoot(tmpConfig);
            }
            data = await this._loadData(tmpConfig);
        }
        Object.assign(config, tmpConfig);
        if (data && commit) {
            commit(data);
        }
        if (reload && config.isRoot) {
            await this.hooks.lifecycle.onRootLoaded(this.root);
        }
    }

    /**
     *
     * @param {RelationalModelConfig} config
     * @returns {Promise<number>}
     */
    async _updateCount(config) {
        const count = await this.keepLast.add(
            this.orm.searchCount(config.resModel, config.domain, {
                context: config.context,
            }),
        );
        config.countLimit = Number.MAX_SAFE_INTEGER;
        return count;
    }

    /**
     * When grouped by a many2many field, the same record may be displayed in
     * several groups. When one of these records is edited, we want all other
     * occurrences to be updated. The purpose of this function is to find and
     * update all occurrences of a record that has been reloaded, in a grouped
     * list view.
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
        if (!this.initialSampleGroups) {
            this.initialSampleGroups = deepCopy(result.groups);
        }
        return result;
    }
}
