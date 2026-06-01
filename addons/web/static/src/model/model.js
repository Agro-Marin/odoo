// @ts-check
/** @odoo-module native */

/** @module @web/model/model - Abstract base Model class with OWL lifecycle integration and sample data fallback */

import {
    EventBus,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    status,
    useComponent,
} from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { SEARCH_KEYS } from "@web/core/constants";
import { ModelEvent } from "@web/core/events";
import { RPCError } from "@web/core/network/rpc";
import { Deferred, Race } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { SignalStore } from "@web/core/utils/reactive";
import { featureFlag } from "@web/services/feature_flags";

import { buildSampleORM } from "./sample_server.js";
import { SampleDataCoordinator } from "./sample_data_coordinator.js";
import { validateSearchParams } from "./search_params_schema.js";

/** @import { OdooEnv } from "@web/env" */
/** @import { SearchParams } from "@web/model/types" */
/** @import { ServiceFactories as Services } from "services" */

export class Model extends SignalStore {
    static services = [];

    /**
     * @param {OdooEnv} env
     * @param {Object} params
     * @param {Object} services
     */
    constructor(env, params, services) {
        // ``super()`` returns ``reactive(this)`` (SignalStore semantics), so
        // every assignment below — including ``this.bus``, ``this.data``,
        // ``this.config``, and the ``this.root`` set by subclass ``load()``
        // implementations — goes through the OWL reactive Proxy and notifies
        // observers automatically. Consumers that wrap the model with
        // ``useState(...)`` (form, list, kanban, calendar, graph, pivot)
        // therefore re-render on any mutation without needing an explicit
        // ``model.notify()`` call. The bus + ``notify()`` API is preserved
        // for legacy and cross-addon consumers (FIELD_IS_DIRTY,
        // WILL_SAVE_URGENTLY, NEED_LOCAL_CHANGES, PROPERTY_FIELD:EDIT,
        // SCROLL_TO_CURRENT_HOUR, and the ModelEvent.UPDATE listeners in
        // ``x2many_dialog`` and ``calendar_controller``) but is no longer
        // load-bearing for the local re-render path.
        super();
        this.env = env;
        this.orm = services.orm;
        this.bus = new EventBus();
        this.isReady = false;
        /**
         * Observable sample-data state. Read via {@link useSampleModel}
         * getter for backward-compat across the 11 historical reader
         * sites; write via ``this.sampleData.enter()`` / ``.exit()``
         * (or the legacy ``this.useSampleModel = bool`` setter for the
         * two existing PivotModel / GraphModel write sites).
         *
         * @type {SampleDataCoordinator}
         */
        this.sampleData = new SampleDataCoordinator();
        /**
         * The root data point, set by subclass `load()` implementations
         * (e.g. a Record, DynamicRecordList, or DynamicGroupList).
         * @type {any}
         */
        this.root = undefined;
        /**
         * Model metadata, set by subclass implementations
         * (e.g. GraphModel, PivotModel).
         * @type {any}
         */
        this.metaData = undefined;
        /**
         * Model data, set by subclass implementations
         * (e.g. PivotModel, GraphModel).
         * @type {any}
         */
        this.data = undefined;
        /**
         * Model configuration, set by subclass implementations
         * (e.g. RelationalModel).
         * @type {any}
         */
        this.config = undefined;
        /** @type {Deferred} */
        this.whenReady = new Deferred();
        this.whenReady.then(() => {
            // Idempotent: ``RelationalModel.load`` already sets
            // ``isReady = true`` in the SAME synchronous block as its
            // ``root`` / ``config`` writes (so OWL batches all three
            // reactive invalidations into a single render — the previous
            // out-of-band write in this ``.then()`` callback fired in a
            // later microtask separated by ``await onRootLoaded`` and
            // produced an extra render visible to ``onRendered`` step
            // assertions).  For subclasses that DON'T set ``isReady`` in
            // ``load`` (PivotModel, GraphModel, CalendarModel), this is
            // still the only place that flips the flag, so the search-
            // panel/pivot integration in test_search keeps working.
            // ``notify()`` is intentionally NOT called here — the
            // reactive write to ``isReady`` and the subclass-emitted
            // writes during ``load`` already invalidate every consumer
            // that wraps the model in ``useState``.
            this.isReady = true;
        });
        this.setup(params, services);
    }

    /**
     * @param {Object} _params
     * @param {Object} _services
     */
    setup(_params, _services) {}

    /**
     * Backward-compat alias for ``sampleData.isActive``. The 11
     * historical readers across views/ (pivot_controller, list_renderer,
     * list_keyboard_nav, list_controller, list_styling, kanban
     * renderer, etc.) continue to work unchanged via this getter; new
     * code should prefer ``model.sampleData.isActive``.
     *
     * @returns {boolean}
     */
    get useSampleModel() {
        return this.sampleData.isActive;
    }

    /**
     * Backward-compat alias for ``sampleData.set(value)``. Used by the
     * two write sites in {@link PivotModel} and {@link GraphModel}
     * that historically did ``this.useSampleModel = false``.
     *
     * @param {boolean} value
     */
    set useSampleModel(value) {
        this.sampleData.set(value);
    }

    /**
     * @param {Partial<SearchParams>} [_params]
     */
    async load(_params) {}

    /**
     * This function is meant to be overriden by models that want to implement
     * the sample data feature. It should return true iff the last loaded state
     * actually contains data. If not, another load will be done (if the sample
     * feature is enabled) with the orm service substituted by another using the
     * SampleServer, to have sample data to display instead of an empty screen.
     *
     * @returns {boolean}
     */
    hasData() {
        return true;
    }

    /**
     * This function is meant to be overriden by models that want to combine
     * sample data with real groups that exist on the server.
     *
     * @returns {boolean}
     */
    getGroups() {
        return null;
    }

    notify() {
        this.bus.trigger(ModelEvent.UPDATE);
    }
}

/**
 * @param {Record<string, unknown>} props
 * @returns {Object}
 */
function getSearchParams(props) {
    const params = {};
    for (const key of SEARCH_KEYS) {
        params[key] = props[key];
    }
    if (_isSearchParamsValidationEnabled()) {
        const issues = validateSearchParams(params);
        if (issues.length) {
            // Warn-only: a contract drift never blocks the load. The
            // warning surfaces in dev / when the feature flag is on so
            // we get a signal long before the silent ride-along becomes
            // load-bearing in production.
            console.warn(
                `[search-params] ${issues.length} issue(s) at useModel boundary:\n  - ` +
                    issues.join("\n  - "),
            );
        }
    }
    return params;
}

/**
 * Cached one-shot check.  Validation is opt-in (off in production by
 * default to keep the boundary path free of allocation overhead on
 * every load).  Three activation sources, in order:
 *
 *   1. ``odoo.debug`` mode — any debug truthy value auto-enables so
 *      developers don't need to remember the flag.
 *   2. ``featureFlag("search_params_validation")`` — explicit opt-in
 *      for staged rollout. Resolution honors the URL > localStorage >
 *      server cascade documented in ``services/feature_flags``.
 *   3. Both ``false`` → validator skipped entirely.
 *
 * Cached because the answer never changes within a session — URL and
 * localStorage are read once by the feature-flags resolver, and
 * ``odoo.debug`` is fixed for the page lifetime.
 *
 * @returns {boolean}
 */
let _searchParamsValidationCache = null;
function _isSearchParamsValidationEnabled() {
    if (_searchParamsValidationCache !== null) {
        return _searchParamsValidationCache;
    }
    _searchParamsValidationCache = Boolean(
        odoo.debug ||
            featureFlag("search_params_validation", { default: false }),
    );
    return _searchParamsValidationCache;
}

/**
 * Test-only: reset the validation-cache so a stubbed feature flag /
 * debug mode is re-read on the next call.  Production code never
 * needs this (the answer is fixed for the page lifetime).
 */
export function _resetSearchParamsValidationCache() {
    _searchParamsValidationCache = null;
}

/**
 * @param {typeof Model} ModelClass
 * @param {Object} params
 * @param {Object} [options]
 * @param {Function} [options.beforeFirstLoad]
 * @returns {Model}
 */
export function useModel(ModelClass, params, options = {}) {
    const component = useComponent();
    /** @type {Record<string, any>} */
    const services = {};
    for (const key of ModelClass.services) {
        services[key] = useService(key);
    }
    services.orm = services.orm || useService("orm");
    const model = new ModelClass(/** @type {any} */ (component.env), params, services);
    onWillStart(async () => {
        await options.beforeFirstLoad?.();
        await model.load(getSearchParams(component.props));
        model.whenReady.resolve();
    });
    onWillUpdateProps((nextProps) => model.load(getSearchParams(nextProps)));
    return model;
}

/**
 * @param {typeof Model} ModelClass
 * @param {Object} params
 * @param {Object} [options]
 * @param {Function} [options.lazy=false]
 * @returns {Model}
 */
export function useModelWithSampleData(ModelClass, params, options = {}) {
    const component = useComponent();
    if (!(ModelClass.prototype instanceof Model)) {
        throw new Error(`the model class should extend Model`);
    }
    /** @type {Record<string, any>} */
    const services = {};
    for (const key of ModelClass.services) {
        services[key] = useService(key);
    }
    services.orm = services.orm || useService("orm");

    if (!("isAlive" in params)) {
        params.isAlive = () => status(component) !== "destroyed";
    }

    const model = new ModelClass(/** @type {any} */ (component.env), params, services);

    // Manual re-render listener — retained for backward compatibility with
    // consumers that do NOT wrap the model with ``useState(...)`` (in
    // particular several enterprise addons: ``web_map``, ``web_cohort``,
    // ``web_grid``, ``web_gantt``, ``social``).
    //
    // As of 2026-05-25, ``Model extends SignalStore`` (see ``model.js``
    // class declaration), so consumers that DO wrap with ``useState(...)``
    // — calendar, graph, pivot, plus form/list/kanban via their own
    // controllers — already receive proxy-based reactive renders on every
    // mutation. The bus listener below then schedules a redundant
    // ``render(true)`` on each ``notify()`` call; OWL batches both into
    // one render per tick, so there is no observable double-render. If a
    // future audit confirms every consumer wraps with ``useState`` (or
    // an equivalent reactive subscription path), this listener can go.
    const onUpdate = () => component.render(true);
    model.bus.addEventListener(ModelEvent.UPDATE, onUpdate);
    onWillUnmount(() => model.bus.removeEventListener(ModelEvent.UPDATE, onUpdate));

    const globalState = component.props.globalState || {};
    const localState = component.props.state || {};
    let useSampleModel =
        component.props.useSampleModel &&
        (!("useSampleModel" in globalState) || globalState.useSampleModel);
    model.useSampleModel = false;
    const orm = model.orm;
    // The sampleORM (if persisted from a prior controller) was created with
    // Object.create(oldOrm) where oldOrm was the *previous* component's
    // protected ORM wrapper.  That wrapper rejects when the old component is
    // destroyed, so we must re-parent the sampleORM onto the *current*
    // component's ORM wrapper.
    let sampleORM = localState.sampleORM;
    if (sampleORM) {
        Object.setPrototypeOf(sampleORM, orm);
    }

    /**
     * @param {Record<string, unknown>} props
     */
    async function _load(props) {
        const searchParams = getSearchParams(props);
        await model.load(searchParams);
        if (useSampleModel && !model.hasData()) {
            sampleORM =
                sampleORM ||
                buildSampleORM(component.props.resModel, component.props.fields, orm);
            // Load data with sampleORM then restore real ORM.
            model.orm = sampleORM;
            await model.load(searchParams);
            model.orm = orm;
            model.useSampleModel = true;
        } else {
            useSampleModel = false;
            model.useSampleModel = useSampleModel;
        }
        model.whenReady.resolve(); // resolve after the first successful load
        if (status(component) === "mounted") {
            model.notify();
        }
    }
    const race = new Race();
    const load = (props) => race.add(_load(props));
    onWillStart(() => {
        const prom = load(component.props);
        if (options.lazy) {
            // in-house error handling as we're out of willStart
            prom.catch((e) => {
                if (e instanceof RPCError) {
                    component.env.config.historyBack();
                }
                throw e;
            });
        } else {
            return prom;
        }
    });
    onWillUpdateProps((nextProps) => {
        useSampleModel = false;
        load(nextProps);
    });

    useSetupAction({
        getGlobalState() {
            if (component.props.useSampleModel) {
                return { useSampleModel };
            }
        },
        getLocalState: () => ({ sampleORM }),
    });

    return model;
}

function _makeFieldFromPropertyDefinition(name, definition, relatedPropertyField) {
    return {
        ...definition,
        name,
        propertyName: definition.name,
        relation: definition.comodel,
        relatedPropertyField,
    };
}

export async function addPropertyFieldDefs(orm, resModel, context, fields, groupBy) {
    const proms = [];
    for (const gb of groupBy) {
        if (gb in fields) {
            continue;
        }
        const [fieldName] = gb.split(".");
        const field = fields[fieldName];
        if (field?.type === "properties") {
            proms.push(
                orm
                    .call(resModel, "get_property_definition", [gb], {
                        context,
                    })
                    .then((definition) => {
                        fields[gb] = _makeFieldFromPropertyDefinition(
                            gb,
                            definition,
                            field,
                        );
                    })
                    .catch(() => {
                        fields[gb] = _makeFieldFromPropertyDefinition(gb, {}, field);
                    }),
            );
        }
    }
    return Promise.all(proms);
}
