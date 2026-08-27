// @ts-check
/** @odoo-module native */

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
     * @returns {Promise<void> | void}
     */
    settleBeforeReload() {}

    /**
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
 * @returns {boolean}
 */
function _isSearchParamsValidationEnabled() {
    return (
        Boolean(odoo.debug) ||
        Boolean(featureFlag("search_params_validation", { default: false }))
    );
}

/**
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
 * @param {Model} model
 * @param {Record<string, unknown>} props
 * @returns {Promise<any> | any}
 */
function reloadFromProps(model, props) {
    const load = () => model.load(getSearchParams(props));
    const settling = model.settleBeforeReload();
    return settling ? settling.then(load) : load();
}

/**
 * @param {typeof Model} ModelClass
 * @param {(component: import("@odoo/owl").Component) => Object} buildParams
 * @returns {{ component: import("@odoo/owl").Component, model: Model }}
 */
function makeModel(ModelClass, buildParams) {
    const component = useComponent();
    const services = useModelServices(ModelClass);
    const params = buildParams(component);
    const isAlive = params?.isAlive || (() => status(component) !== "destroyed");
    const model = new ModelClass(
        /** @type {any} */ (component.env),
        { ...params, isAlive },
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
