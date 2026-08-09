// @ts-check
/** @odoo-module native */

/** @module @web/model/model */

import {
    EventBus,
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
import { featureFlag } from "@web/core/feature_flags";
import { RPCError } from "@web/core/network/rpc";
import { Deferred, Race } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";
import { SignalStore } from "@web/core/utils/reactive";

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
        super();
        this.env = env;
        this.orm = services.orm;
        this.bus = new EventBus();
        this.isReady = false;
        /**
         * @type {() => boolean}
         */
        this.isAlive = params?.isAlive || (() => true);
        /**
         * @type {number}
         */
        this._updateEpoch = 0;
        /**
         * @type {SampleDataCoordinator}
         */
        this.sampleData = new SampleDataCoordinator();
        /**
         * @type {any}
         */
        this.root = undefined;
        /**
         * @type {any}
         */
        this.metaData = undefined;
        /**
         * @type {any}
         */
        this.data = undefined;
        /**
         * @type {any}
         */
        this.config = undefined;
        /** @type {Deferred} */
        this.whenReady = new Deferred();
        this.whenReady.then(() => {
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
     * @returns {boolean}
     */
    get useSampleModel() {
        return this.sampleData.isActive;
    }

    /**
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
     * @returns {boolean}
     */
    hasData() {
        return true;
    }

    /**
     * Give a subclass holding uncommitted state a chance to settle before the
     * model is reloaded from new search params. Awaited by both model hooks
     * immediately before `load()`.
     *
     * The base implementation does nothing, and most models need nothing: only
     * a model whose truth is partly outside itself has anything to settle.
     * `RelationalModel` is that model -- field widgets keep the value being
     * typed in closure state and hand it back only when asked -- so it
     * overrides this to drain `_askChanges()` while its mutex is held.
     *
     * Declared here rather than reached for at the call site. Both hooks used
     * to cast the model to `any`, test `mutex.locked` on it, then call
     * `_askChanges` through an optional chain -- the base layer reaching into
     * two private members of one particular subclass, with the cast to get past
     * the type and the `?.` to survive every other Model not having them.
     * Neither `mutex` nor `_askChanges` exists on this class, so nothing
     * declared that contract and nothing would have caught a rename of either.
     *
     * Deliberately NOT `async`, and callers must go through
     * {@link settleThenReload} rather than awaiting it directly. An `async`
     * method returns a promise even when it does nothing, and `await` on it
     * costs a microtask; a reload is on the critical path of every search-facet
     * change, and inserting a tick there reorders the RPCs that follow it. That
     * is not theoretical -- making this `async` and awaiting it unconditionally
     * broke 115 list and kanban tests, all of them on step ordering, because
     * the old code's `if (mutex.locked)` guard meant the idle case never
     * yielded at all. Returning nothing keeps that path synchronous.
     *
     * @returns {Promise<void> | void}
     */
    settleBeforeReload() {}

    /**
     * A counter bumped on every `notify()`. Renderers that cache work derived
     * from the model compare it against the value they last built from, so they
     * rebuild when the model changed and not merely when they re-rendered.
     *
     * Reading it through the reactive proxy also subscribes to it, which is what
     * `useReactiveModel` relies on.
     *
     * @returns {number}
     */
    get updateEpoch() {
        return this._updateEpoch;
    }

    notify() {
        this._updateEpoch++;
        this.bus.trigger(ModelEvent.UPDATE);
    }
}

/**
 * @template {Model} M
 * @param {M} model
 * @returns {M}
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
        if (props[key] !== undefined) {
            params[key] = props[key];
        }
    }
    if (_isSearchParamsValidationEnabled()) {
        const issues = validateSearchParams(params);
        if (issues.length) {
            console.warn(
                `[search-params] ${issues.length} issue(s) at useModel boundary:\n  - ` +
                    issues.join("\n  - "),
            );
        }
    }
    return params;
}

/**
 * Both halves are read live. `featureFlag` resolves against the URL and
 * localStorage on every call precisely so it can be toggled without a reload;
 * memoising the first answer in a module-global made `setFeatureFlag` a no-op
 * for the life of the tab, and leaked the first view's answer across every
 * later test in a run.
 *
 * @returns {boolean}
 */
function _isSearchParamsValidationEnabled() {
    return (
        Boolean(odoo.debug) ||
        Boolean(featureFlag("search_params_validation", { default: false }))
    );
}

/**
 * `useService` is a hook: it must run at the same point of `setup()` in both
 * model hooks, or the `onWillStart` callbacks services register change order
 * and so does the RPC sequence.
 *
 * @param {typeof Model} ModelClass
 * @returns {Record<string, any>}
 */
function useModelServices(ModelClass) {
    /** @type {Record<string, any>} */
    const services = {};
    for (const key of ModelClass.services) {
        services[key] = useService(/** @type {any} */ (key));
    }
    services.orm = services.orm || useService("orm");
    return services;
}

/**
 * Reload the model from a component's props, letting it settle first.
 *
 * The two hooks below reload from three different places between them, and the
 * settle step was spelled out at each one. Naming it once means a model can
 * never be reloaded from props without it -- which was a real hazard, since
 * skipping it silently drops whatever the user was typing.
 *
 * @param {Model} model
 * @param {Record<string, unknown>} props
 * @returns {Promise<any> | any}
 */
function reloadFromProps(model, props) {
    const load = () => model.load(getSearchParams(props));
    const settling = model.settleBeforeReload();
    // Not `await settling` in an async function: awaiting even `undefined`
    // costs a microtask, and the old code reached `load()` synchronously
    // whenever there was nothing to settle. See `Model#settleBeforeReload`.
    return settling ? settling.then(load) : load();
}

/**
 * Build the model, wire it to the component's lifetime, and hand it back.
 *
 * Shared by both hooks. `isAlive` is passed *into* the constructor rather than
 * assigned after it, because `setup()` runs inside the constructor and a
 * subclass reading `this.isAlive` there would otherwise get the default that
 * answers `true` forever. `useModelWithSampleData` already did it this way;
 * `useModel` assigned afterwards, and the two had no reason to differ.
 *
 * `buildParams` is a callback rather than a plain object so the caller can read
 * `component.props` while still letting this function own hook order --
 * `useComponent` and `useModelServices` have to run at the same point in both
 * hooks, per the note on `useModelServices`.
 *
 * @param {typeof Model} ModelClass
 * @param {(component: import("@odoo/owl").Component) => Object} buildParams
 * @returns {{ component: import("@odoo/owl").Component, model: Model }}
 */
function makeModel(ModelClass, buildParams) {
    const component = useComponent();
    const services = useModelServices(ModelClass);
    const isAlive = () => status(component) !== "destroyed";
    const params = buildParams(component);
    const model = new ModelClass(
        /** @type {any} */ (component.env),
        { ...params, isAlive: params?.isAlive || isAlive },
        services,
    );
    model.isAlive = isAlive;
    return { component, model };
}

/**
 * @param {typeof Model} ModelClass
 * @param {Object} params
 * @param {Object} [options]
 * @param {Function} [options.beforeFirstLoad]
 * @returns {Model}
 */
export function useModel(ModelClass, params, options = {}) {
    const { component, model } = makeModel(ModelClass, () => params);
    onWillStart(async () => {
        await options.beforeFirstLoad?.();
        await model.load(getSearchParams(component.props));
        model.whenReady.resolve();
    });
    onWillUpdateProps((nextProps) => reloadFromProps(model, nextProps));
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
    if (!(ModelClass.prototype instanceof Model)) {
        throw new Error(`the model class should extend Model`);
    }
    const { component, model } = makeModel(ModelClass, (comp) => ({
        ...params,
        canUseSampleModel: Boolean(comp.props.useSampleModel),
    }));

    // No blanket subscription here. Propagation is the reactive graph: a
    // controller already wraps the model in `useState`, so its own reads
    // subscribe it, and a component that additionally depends on `notify()`
    // asks for it explicitly with `useReactiveModel` (as `PivotRenderer` and
    // `GraphRenderer` do).
    //
    // What used to live here was a forced render on every model update. A
    // forced render re-renders the whole subtree unconditionally, which defeats
    // the per-row `t-props` invalidation the row components are built around
    // (see `ListRecordRow`), and -- worse -- it silently covers for state that
    // no component actually subscribes to. Removing it surfaced exactly that in
    // the kanban progress bars, where `activeBar` was a getter closed over the
    // seeding proxy and so could never notify a reader; that is now a plain
    // reactive property.
    //
    // Measured on an 80x8 list: sort, pager, search facet, select-all and a
    // single record edit all render identically with and without the blanket,
    // because after a `load()` the datapoints are new and the rows re-render on
    // their own.

    const globalState = component.props.globalState || {};
    const localState = component.props.state || {};
    let useSampleModel =
        component.props.useSampleModel &&
        (!("useSampleModel" in globalState) || globalState.useSampleModel);
    model.useSampleModel = false;
    const orm = model.orm;
    let sampleORM = localState.sampleORM;
    if (sampleORM) {
        Object.setPrototypeOf(sampleORM, orm);
    }

    /**
     * @param {Record<string, unknown>} props
     */
    async function _load(props) {
        const settling = model.settleBeforeReload();
        if (settling) {
            await settling;
        }
        const searchParams = getSearchParams(props);
        await model.load(searchParams);
        if (useSampleModel && !model.hasData()) {
            sampleORM =
                sampleORM ||
                buildSampleORM(component.props.resModel, component.props.fields, orm);
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
        model.whenReady.resolve();
        if (status(component) === "mounted") {
            model.notify();
        }
    }
    const race = new Race();
    const load = (props) => race.add(_load(props));
    onWillStart(() => {
        const prom = load(component.props);
        if (options.lazy) {
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
                        // same fallback as RelationalModel#_getPropertyDefinition:
                        // a field with no type reaches the codecs untyped
                        fields[gb] = _makeFieldFromPropertyDefinition(
                            gb,
                            { type: "char" },
                            field,
                        );
                    }),
            );
        }
    }
    return Promise.all(proms);
}
