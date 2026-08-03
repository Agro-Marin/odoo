// @ts-check
/** @odoo-module native */

/** @module @web/model/model */

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
 * @param {typeof Model} ModelClass
 * @param {Object} params
 * @param {Object} [options]
 * @param {Function} [options.beforeFirstLoad]
 * @returns {Model}
 */
export function useModel(ModelClass, params, options = {}) {
    const component = useComponent();
    const services = useModelServices(ModelClass);
    const model = new ModelClass(/** @type {any} */ (component.env), params, services);
    model.isAlive = () => status(component) !== "destroyed";
    onWillStart(async () => {
        await options.beforeFirstLoad?.();
        await model.load(getSearchParams(component.props));
        model.whenReady.resolve();
    });
    onWillUpdateProps(async (nextProps) => {
        if (/** @type {any} */ (model).mutex?.locked) {
            await /** @type {any} */ (model)._askChanges?.();
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
    const services = useModelServices(ModelClass);

    const modelParams = {
        ...params,
        canUseSampleModel: Boolean(component.props.useSampleModel),
    };
    if (!("isAlive" in modelParams)) {
        modelParams.isAlive = () => status(component) !== "destroyed";
    }

    const model = new ModelClass(
        /** @type {any} */ (component.env),
        modelParams,
        services,
    );

    if (!(/** @type {any} */ (ModelClass).reactiveRenderers)) {
        const onUpdate = () => component.render(true);
        model.bus.addEventListener(ModelEvent.UPDATE, onUpdate);
        onWillDestroy(() => model.bus.removeEventListener(ModelEvent.UPDATE, onUpdate));
    }

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
        if (/** @type {any} */ (model).mutex?.locked) {
            await /** @type {any} */ (model)._askChanges?.();
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
