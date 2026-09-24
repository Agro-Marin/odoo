/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { zip } from "@web/core/utils/collections/arrays";
import { SignalStore } from "@web/core/utils/reactive";
function parseParams(matches, paramSpecs) {
    return Object.fromEntries(
        zip(matches, paramSpecs).map(([match, paramSpec]) => {
            const { type, name } = paramSpec;
            switch (type) {
                case "int":
                    return [name, parseInt(match)];
                case "string":
                    return [name, match];
                default:
                    throw new Error(`Unknown type ${type}`);
            }
        }),
    );
}

export class SelfOrderRouter extends SignalStore {
    static serviceDependencies = [];

    constructor(...args) {
        super(...args);
        this.setup(...args);
    }

    setup(env) {
        this.registeredRoutes = {};
        this.historyPage = "";
        this.activeSlot = null;
        this.slotParams = {};
        this.path = window.location.pathname;
        window.addEventListener("popstate", (event) => {
            this.path = window.location.pathname;
        });
    }

    addTableIdentifier(table) {
        const url = new URL(browser.location.href);
        url.searchParams.set("table_identifier", table.identifier);
        history.replaceState({}, "", url);
    }

    getTableIdentifier() {
        const url = new URL(browser.location.href);
        return url.searchParams.get("table_identifier");
    }

    back() {
        if (!this.historyPage.length) {
            // We use the browser history, so if the user arrives on a page with a back button from a link,
            // we don't know the previous page, so we send them back to the beginning of the feed.
            this.navigate("default");
            return;
        }

        history.back();
        this.path = window.location.pathname;
        this.historyPage = window.location.pathname;
    }

    /**
     * Navigate to the given relative route.
     * We use the history API to navigate to it.
     * (this means that we don't make additional requests to the server)
     * @param {string} route
     */
    navigate(routeName, routeParams = {}) {
        const { route } = this.registeredRoutes[routeName];
        const url = new URL(browser.location.href);

        url.pathname = route.replace(
            /\{\w+:(\w+)\}/g,
            (match, paramName) => routeParams[paramName],
        );

        history.pushState({}, "", url);
        this.path = window.location.pathname;
        this.historyPage = this.path;
    }

    get path() {
        return this._path;
    }

    set path(path) {
        this._path = path;
        this.syncRoute();
    }

    registerRoutes(routes) {
        Object.assign(this.registeredRoutes, routes);
        this.syncRoute();
    }

    syncRoute() {
        for (const [routeName, { paramSpecs, regex }] of Object.entries(
            this.registeredRoutes,
        )) {
            const match = regex && this._path.match(regex);
            if (match) {
                this.activeSlot = routeName;
                this.slotParams = parseParams(match.slice(2), paramSpecs);
                return;
            }
        }
        if (!Object.keys(this.registeredRoutes).length) {
            return;
        }
        this.activeSlot = "default";
        this.slotParams = {};
        if (this.registeredRoutes.default && !this._redirecting) {
            this._redirecting = true;
            try {
                this.navigate("default");
            } finally {
                this._redirecting = false;
            }
        }
    }

    // If the url isn't a valid URL, we assume it's a relative path
    customLink(link) {
        let url;

        try {
            url = new URL(link.url);
            window.open(url);
        } catch {
            url = new URL(browser.location.href);
            url.pathname = link.url;

            history.pushState({}, "", url);
            this.path = window.location.pathname;
            this.historyPage = this.path;
        }
    }
}

export const SelfOrderRouterService = {
    dependencies: SelfOrderRouter.serviceDependencies,
    async start(env, deps) {
        return new SelfOrderRouter(env, deps);
    },
};

registry.category("services").add("router", SelfOrderRouterService);
