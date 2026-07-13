// @ts-check
/** @odoo-module native */

/** @module @web/model/model - Abstract base Model class with OWL lifecycle integration and sample data fallback */

import {
    EventBus,
    onWillDestroy,
    onWillRender,
    onWillStart,
    onWillUpdateProps,
    status,
    useComponent,
    useState,
} from "@odoo/owl";
import { useSetupAction } from "@web/core/action_hook";
import { SEARCH_KEYS } from "@web/core/constants";
import { ModelEvent } from "@web/core/events";
import { RPCError } from "@web/core/network/rpc";
import { Deferred, Race } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { SignalStore } from "@web/core/utils/reactive";
import { featureFlag } from "@web/services/feature_flags";

import { SampleDataCoordinator } from "./sample_data_coordinator.js";
import { buildSampleORM } from "./sample_server.js";
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
        // every assignment below goes through OWL's reactive Proxy and
        // notifies consumers that wrap the model in ``useState()``
        // automatically — no explicit ``notify()`` needed for local
        // mutations. The bus + ``notify()`` API remains for legacy/cross-addon
        // consumers (FIELD_IS_DIRTY, WILL_SAVE_URGENTLY, NEED_LOCAL_CHANGES,
        // PROPERTY_FIELD:EDIT, SCROLL_TO_CURRENT_HOUR, and the
        // ModelEvent.UPDATE listeners in x2many_dialog / calendar_controller).
        super();
        this.env = env;
        this.orm = services.orm;
        this.bus = new EventBus();
        this.isReady = false;
        /**
         * Bumped by every ``notify()`` — the reactive key
         * ``useReactiveModel`` subscribes renderers to.
         * @type {number}
         */
        this._updateEpoch = 0;
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
            // No-op for RelationalModel (``load()`` already sets isReady in the
            // same sync block as root/config, avoiding an extra render); still
            // the only place that flips it for Pivot/Graph/Calendar models,
            // which don't set isReady in ``load()``. ``notify()`` isn't needed:
            // the reactive write to isReady already invalidates useState consumers.
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
     * Override to implement sample data: return true iff the last loaded
     * state contains data. If false (and the feature is enabled), another
     * load is done with the orm substituted by a SampleServer-backed one,
     * to show sample data instead of an empty screen.
     *
     * @returns {boolean}
     */
    hasData() {
        return true;
    }

    /**
     * Override to combine sample data with real groups that exist on the
     * server.
     *
     * @returns {boolean}
     */
    getGroups() {
        return null;
    }

    notify() {
        // Reactive update signal: renderers subscribed via
        // ``useReactiveModel`` re-render on this bump without the
        // legacy deep-render bus listener (see ``reactiveRenderers``).
        this._updateEpoch++;
        this.bus.trigger(ModelEvent.UPDATE);
    }
}

/**
 * Subscribes the current component to a model's ``notify()`` signal and
 * returns a component-bound reactive view of the model.
 *
 * Use this in renderers that snapshot derived state from the model
 * (e.g. PivotRenderer's ``getTable()``): reading ``_updateEpoch`` during
 * render subscribes the component, so every ``model.notify()`` re-renders
 * it directly — no parent deep render required. Model classes whose whole
 * view tree relies on this pattern opt out of the legacy listener with
 * ``static reactiveRenderers = true``.
 *
 * @template {Model} M
 * @param {M} model
 * @returns {M} component-bound reactive proxy of ``model``
 */
export function useReactiveModel(model) {
    const reactiveModel = useState(model);
    onWillRender(() => void reactiveModel._updateEpoch);
    return reactiveModel;
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
 * Cached one-shot check. Validation is opt-in (off by default in production
 * to avoid per-load overhead). Three activation sources, in order:
 *
 *   1. ``odoo.debug`` truthy → auto-enables.
 *   2. ``featureFlag("search_params_validation")`` — explicit opt-in for
 *      staged rollout (URL > localStorage > server cascade).
 *   3. Both ``false`` → validator skipped.
 *
 * Cached because the answer never changes within a session.
 *
 * @returns {boolean}
 */
let _searchParamsValidationCache = null;
function _isSearchParamsValidationEnabled() {
    if (_searchParamsValidationCache !== null) {
        return _searchParamsValidationCache;
    }
    _searchParamsValidationCache = Boolean(
        odoo.debug || featureFlag("search_params_validation", { default: false }),
    );
    return _searchParamsValidationCache;
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
    onWillUpdateProps(async (nextProps) => {
        // Drain an in-flight mutex'd save before reloading the root: a
        // search-driven load racing a save would otherwise render pre-save
        // values and detach the old root while the save's response updates
        // it. Gated on ``mutex.locked`` so the idle path keeps its exact
        // microtask timing (dozens of tests pin RPC step order). Internal,
        // mutex-held load() callers (record_lifecycle) must NOT drain —
        // they would deadlock — which is why this sits at the props
        // boundary instead of load().
        if (/** @type {any} */ (model).mutex?.locked) {
            await model._askChanges?.();
        }
        return model.load(getSearchParams(nextProps));
    });
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

    // Sample-data *capability* (not the runtime ``model.useSampleModel`` state):
    // whether sample data can ever activate for this model. It is the necessary
    // condition for the sample branch below (``component.props.useSampleModel &&
    // ...``), so RelationalModel uses it to skip snapshotting initialSampleGroups
    // on the first (real) load of the overwhelmingly common non-sample view —
    // that snapshot is a deep clone consumed only when the sample branch runs.
    params.canUseSampleModel = Boolean(component.props.useSampleModel);

    const model = new ModelClass(/** @type {any} */ (component.env), params, services);

    // Legacy deep-render listener. CAUTION: still load-bearing for any
    // renderer that (a) receives the model as a stable prop (OWL's
    // props-equality skips reactive controller renders) and (b) snapshots
    // derived state in onWillUpdateProps/useEffect deps — pivot/graph did
    // until migrating to useReactiveModel + ``reactiveRenderers = true``.
    // Still depends on it: calendar, enterprise web_map/web_cohort/
    // web_grid/web_gantt/social. Audit (a)+(b) before opting a model out.
    if (!(/** @type {any} */ (ModelClass).reactiveRenderers)) {
        const onUpdate = () => component.render(true);
        model.bus.addEventListener(ModelEvent.UPDATE, onUpdate);
        // onWillDestroy (not onWillUnmount): unmount hooks don't fire for a
        // component destroyed BEFORE it mounts, which would leak the listener
        // (and a load resolving after early destruction would call
        // component.render on a destroyed component). Same rule navbar /
        // action_container / command_palette already follow.
        onWillDestroy(() => model.bus.removeEventListener(ModelEvent.UPDATE, onUpdate));
    }

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
        // Same save/load race guard as useModel's onWillUpdateProps; no-op
        // for model classes without a mutex (graph, pivot) and when idle.
        if (/** @type {any} */ (model).mutex?.locked) {
            await /** @type {any} */ (model)._askChanges?.();
        }
        const searchParams = getSearchParams(props);
        await model.load(searchParams);
        if (useSampleModel && !model.hasData()) {
            sampleORM =
                sampleORM ||
                buildSampleORM(component.props.resModel, component.props.fields, orm);
            // Load data with sampleORM then restore real ORM — even on throw
            // (e.g. UnimplementedRouteError), or every later action would
            // keep routing to the in-memory fake.
            model.orm = sampleORM;
            try {
                await model.load(searchParams);
            } finally {
                model.orm = orm;
            }
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
