// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
const cogMenuRegistry = registry.category("cogMenu");

const moduleUpdateCache = new WeakMap();

export class ResetModuleStateCogMenu extends Component {
    static template = "web.ResetModuleStateCogMenu";
    static components = { DropdownItem };
    static props = {};

    /** @type {import("services").ServiceFactories["orm"]} */
    orm;

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
        /** @param {{ config: any, searchModel: any, services: any }} param0 */
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
