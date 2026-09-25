// @ts-check
/** @odoo-module native */

import { App, Component, EventBus } from "@odoo/owl";
import { isCtrlOrCmdKey } from "@web/core/browser/hotkeys";
import { makeLogger } from "@web/core/debug/debug_logger";
import { AppEvent } from "@web/core/events";
import { ServiceContainer } from "@web/core/service_container";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";
import { componentLog, makeAssetLog } from "@web/core/utils/asset_log";
import { session } from "@web/session";

const log = makeAssetLog("env");
/**
 * A component mounted with the web environment may require its services,
 * while a reusable Owl component may only expose the base environment.
 * @template [P=any]
 * @typedef {new (props: P, env: OdooEnv) => Component<P>} OdooComponentConstructor
 */

/**
 * @typedef {{
 * bus: EventBus;
 * debug: string;
 * services: import("services").ServiceFactories;
 * readonly isSmall: boolean;
 * config?: Record<string, any>;
 * [key: string]: any;
 * }} OdooEnv
 */

const debugLog = makeLogger("web.env");

/** @returns {OdooEnv} */
export function makeEnv() {
    debugLog.lifecycle("makeEnv", () => ({ debug: odoo.debug }));
    log("makeEnv: creating OdooEnv — debug=", odoo.debug || "(empty)");
    const bus = new EventBus();
    const prom = new Promise((resolve) => {
        bus.addEventListener(AppEvent.SERVICES_LOADED, resolve, { once: true });
    });
    const env = /** @type {any} */ ({
        bus,
        isReady: prom,
        services: {},
        debug: odoo.debug,
        get isSmall() {
            throw new Error("UI service not initialized!");
        },
        destroy() {
            serviceContainerOf(env).destroy();
        },
    });
    containersByServices.set(env.services, new ServiceContainer(env));
    return env;
}

/** @type {WeakMap<object, ServiceContainer>} */
const containersByServices = new WeakMap();

/**
 * @param {Record<string, any>} env
 * @returns {ServiceContainer}
 */
export function serviceContainerOf(env) {
    for (
        let services = env.services;
        services;
        services = Object.getPrototypeOf(services)
    ) {
        const container = containersByServices.get(services);
        if (container) {
            return container;
        }
    }
    throw new Error(
        "This env's services were not made by makeEnv(): it has no service container",
    );
}

/**
 * @param {OdooEnv} env
 * @returns {Promise<void>}
 */
export function startServices(env) {
    return serviceContainerOf(env).start();
}

/**
 * @param {OdooEnv} env
 * @returns {Promise<void>}
 */
export function startMissingServices(env) {
    return serviceContainerOf(env).startMissing();
}

export const customDirectives = {
    click: (node, value, modifiers) => {
        let mods = "";
        if (modifiers.includes("synthetic")) {
            mods += ".synthetic";
        }
        if (modifiers.includes("capture")) {
            mods += ".capture";
        }
        const hasStop = modifiers.includes("stop");
        const hasPrevent = modifiers.includes("prevent");
        const handlerFunction = `(ev) => __globals__.click(ev, (${value}).bind(this), ${hasStop}, ${hasPrevent})`;
        node.setAttribute(`t-on-click${mods}`, handlerFunction);
        node.setAttribute(`t-on-auxclick${mods}`, handlerFunction);
    },
};

export const globalValues = {
    /**
     * @param {MouseEvent} ev
     * @param {Function} value
     * @param {boolean} hasStop
     * @param {boolean} hasPrevent
     */
    click: (ev, value, hasStop, hasPrevent) => {
        if (ev.button === 0 || ev.button === 1) {
            if (hasStop) {
                ev.stopPropagation();
            }
            if (hasPrevent) {
                ev.preventDefault();
            }
            const ctrlKey = isCtrlOrCmdKey(ev);
            const isMiddleClick = (ctrlKey && ev.button === 0) || ev.button === 1;
            return value(ev, isMiddleClick);
        }
    },
};

/**
 * @param {import("@odoo/owl").Env | undefined} env
 * @param {Record<string, any>} [overrides]
 * @returns {Record<string, any>}
 */
export function makeAppConfig(env, overrides = {}) {
    return {
        env,
        getTemplate,
        dev: Boolean(/** @type {any} */ (env)?.debug || session.test_mode),
        warnIfNoStaticProps: !session.test_mode,
        translatableAttributes: ["data-tooltip"],
        translateFn: appTranslateFn,
        customDirectives,
        globalValues,
        ...overrides,
    };
}

/**
 * @param {import("@odoo/owl").ComponentConstructor} component
 * @param {HTMLElement | ShadowRoot} target
 * @param {Partial<ConstructorParameters<typeof App>[1]> & {
 * beforeMount?: (env: OdooEnv) => void | Promise<void>
 * }} [appConfig]
 */
export async function mountComponent(component, target, appConfig = {}) {
    const { beforeMount, ...owlConfig } = appConfig;
    let { env } = appConfig;
    const isRoot = !env;
    log(
        "mountComponent:",
        component.name || "anon",
        "isRoot=",
        isRoot,
        "target=",
        "tagName" in target ? target.tagName : "#shadow-root",
    );
    if (isRoot) {
        env = makeEnv();
        await startServices(/** @type {OdooEnv} */ (env));
    }
    const endMount = debugLog.perf(`mount ${component.name || "anon"}`);
    const app = new App(
        component,
        makeAppConfig(env, { name: component.name, ...owlConfig }),
    );
    if (isRoot) {
        Component.env = app.env;
        if (!(/** @type {any} */ (app).dev)) {
            /** @type {any} */ (env).services.template_compile_cache?.install(app);
        }
    }
    await beforeMount?.(/** @type {OdooEnv} */ (app.env));
    componentLog("mount", component.name || "anon", "isRoot=", isRoot);
    const root = await app.mount(target);
    endMount({ isRoot });
    if (isRoot) {
        /** @type {any} */ (odoo).__WOWL_DEBUG__ = { root };
    }
    return app;
}
