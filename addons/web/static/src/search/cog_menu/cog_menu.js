// @ts-check
/** @odoo-module native */

/** @module @web/search/cog_menu/cog_menu */

import { onWillStart, onWillUpdateProps } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { ActionMenus } from "@web/search/action_menus/action_menus";

const cogMenuRegistry = registry.category("cogMenu");

cogMenuRegistry.addValidation({
    Component: Function,
    groupNumber: { type: Number, optional: true },
    isDisplayed: { type: Function, optional: true },
    "*": true,
});

/**
 * @extends ActionMenus
 */
// @ts-expect-error - static props/defaultProps shapes differ from parent (OWL pattern)
export class CogMenu extends ActionMenus {
    static template = "web.CogMenu";
    static components = {
        ...ActionMenus.components,
        Dropdown,
    };
    static props = {
        ...ActionMenus.props,
        getActiveIds: { type: ActionMenus.props.getActiveIds, optional: true },
        context: { type: ActionMenus.props.context, optional: true },
        resModel: { type: ActionMenus.props.resModel, optional: true },
        items: { ...ActionMenus.props.items, optional: true },
        slots: { type: Object, optional: true },
    };
    static defaultProps = {
        ...ActionMenus.defaultProps,
        items: {},
    };

    /** @type {any[]} */
    registryItems;

    setup() {
        super.setup();
        onWillStart(async () => {
            this.registryItems = await this._registryItems();
        });
        onWillUpdateProps(async () => {
            this.registryItems = await this._registryItems();
        });
    }

    /** @returns {boolean} */
    get hasItems() {
        return this.cogItems.length || this.props.items.print?.length;
    }

    /**
     * @returns {Promise<Array<{Component: import("@odoo/owl").ComponentConstructor, groupNumber: number, key: string}>>}
     */
    async _registryItems() {
        const registryItems = cogMenuRegistry.getAll();
        const areDisplayed = await Promise.all(
            registryItems.map((item) =>
                "isDisplayed" in item
                    ? /** @type {Function} */ (item.isDisplayed)(
                          /** @type {import("@web/env").OdooEnv} */ (this.env),
                      )
                    : true,
            ),
        );
        const items = [];
        for (let i = 0; i < registryItems.length; i++) {
            if (areDisplayed[i]) {
                const item = registryItems[i];
                items.push({
                    Component: item.Component,
                    groupNumber: item.groupNumber,
                    key: item.Component.name,
                });
            }
        }
        return items;
    }

    /**
     * @returns {Array<
     *   | {Component: import("@odoo/owl").ComponentConstructor, groupNumber: number, key: string}
     *   | {key: string, groupNumber: number, description?: string, action?: any, callback?: Function}
     * >}
     */
    get cogItems() {
        return [...this.registryItems, ...(this.actionItems ?? [])].toSorted(
            (item1, item2) => (item1.groupNumber || 0) - (item2.groupNumber || 0),
        );
    }

    /**
     * @param {{ description: string }} item
     * @returns {string}
     */
    getPrintItemAriaLabel(item) {
        return _t("Print report: %s", item.description);
    }
}
