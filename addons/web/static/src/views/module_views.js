// @ts-check
/** @odoo-module native */

/** @module @web/views/module_views - Cog-menu item to reset ir.module.module installation state */

import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const cogMenuRegistry = registry.category("cogMenu");

// ``check_module_update`` is evaluated by the CogMenu on both ``onWillStart``
// and every ``onWillUpdateProps``. Memoize its result per action controller
// (keyed by the stable ``env.config`` object) so the RPC runs at most once per
// Apps view instead of on every props update. The WeakMap lets stale entries
// be garbage-collected when the controller is disposed.
const moduleUpdateCache = new WeakMap();

/** Cog-menu item that resets module installation state (only on ir.module.module list views). */
export class ResetModuleStateCogMenu extends Component {
    static template = "web.ResetModuleStateCogMenu";
    static components = { DropdownItem };
    static props = {};

    setup() {
        this.orm = useService("orm");
    }

    async resetModuleState() {
        await this.orm.call("ir.module.module", "button_reset_state", [], {});
        browser.location.reload();
    }
}

cogMenuRegistry.add(
    "reset-module-state-cog-menu",
    /** @type {any} */ ({
        Component: ResetModuleStateCogMenu,
        isDisplayed: async ({ config, searchModel, services }) => {
            if (
                searchModel.resModel !== "ir.module.module" ||
                config.viewType === "form"
            ) {
                return false;
            }
            if (!moduleUpdateCache.has(config)) {
                moduleUpdateCache.set(
                    config,
                    (async () => {
                        try {
                            // ``silent`` + swallow: a rejected background RPC
                            // must not crash the whole Apps view (nor pop an
                            // error dialog) — just hide the cog item.
                            return Boolean(
                                await services.orm.silent.call(
                                    "ir.module.module",
                                    "check_module_update",
                                    [],
                                    {},
                                ),
                            );
                        } catch {
                            return false;
                        }
                    })(),
                );
            }
            return moduleUpdateCache.get(config);
        },
    }),
);
