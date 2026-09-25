// @ts-check
/** @odoo-module native */

import { onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useSearchModel } from "@web/core/search_model_hooks";
import { useActiveElementScope } from "@web/core/utils/active_element_scope";
import { useOptionalService } from "@web/core/utils/hooks";

/**
 * @typedef {import("@web/search/search_model").SearchModel} SearchModel
 * @typedef {{
 *   config: Record<string, any>,
 *   searchModel: SearchModel,
 *   controller: any,
 * }} ActiveView
 * @typedef {ActiveView & { scope: () => Document | HTMLElement }} ActiveViewEntry
 */

export class ActiveViews {
    /** @param {{ activeElement: Document | HTMLElement }} ui */
    constructor(ui) {
        this.ui = ui;
        /** @type {ActiveViewEntry[]} */
        this.entries = [];
    }

    /**
     * @param {ActiveViewEntry} entry
     * @returns {() => void}
     */
    add(entry) {
        this.entries.push(entry);
        return () => {
            const index = this.entries.indexOf(entry);
            if (index !== -1) {
                this.entries.splice(index, 1);
            }
        };
    }

    /**
     * @param {ActiveView} view
     * @returns {boolean} whether that view is still mounted
     */
    has(view) {
        return this.entries.includes(/** @type {ActiveViewEntry} */ (view));
    }

    // children mount before their parents, so an embedded view registers
    // before the view that holds it: the last entry in the active element is
    // the outermost view the user is looking at
    /** @returns {ActiveView | null} */
    get current() {
        const active = this.ui.activeElement;
        for (let index = this.entries.length - 1; index >= 0; index--) {
            const entry = this.entries[index];
            if (entry.scope() === active) {
                return entry;
            }
        }
        return null;
    }
}

export const activeViewService = {
    dependencies: ["ui"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ ui: { activeElement: Document | HTMLElement } }} services
     */
    start(env, { ui }) {
        return new ActiveViews(ui);
    },
};

/** @type {WeakMap<SearchModel, any>} */
const CONTROLLERS = new WeakMap();

/**
 * @param {Record<string, any>} config
 * @param {SearchModel} searchModel
 */
export function provideActiveView(config, searchModel) {
    const activeViews = useOptionalService("active_view");
    const scope = useActiveElementScope();
    if (!activeViews) {
        return;
    }
    /** @type {ActiveViewEntry} */
    const entry = {
        config,
        searchModel,
        scope,
        get controller() {
            return CONTROLLERS.get(searchModel) ?? null;
        },
    };
    /** @type {() => void} */
    let remove = () => {};
    onMounted(() => {
        remove = activeViews.add(entry);
    });
    onWillUnmount(() => remove());
}

/** @param {any} controller */
export function useActiveViewController(controller) {
    const searchModel = useSearchModel();
    if (searchModel && !CONTROLLERS.has(searchModel)) {
        CONTROLLERS.set(searchModel, controller);
    }
}

registry.category("services").add("active_view", activeViewService);
