// @ts-check
/** @odoo-module native */

/** @module @web/search/cog_menu/cog_menu - Combined cog dropdown merging Action, Print, and registry-based menu items */

import { onWillStart, onWillUpdateProps } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ActionMenus } from "@web/search/action_menus/action_menus";

const cogMenuRegistry = registry.category("cogMenu");

// Cog-menu items appear in the controller's gear menu.
// Same shape as favoriteMenu: a Component plus optional grouping/visibility.
cogMenuRegistry.addValidation({
    Component: Function,
    groupNumber: { type: Number, optional: true },
    isDisplayed: { type: Function, optional: true },
    "*": true,
});

/**
 * ActionMenus variant merging Action, Print, and registry-based cog items into a
 * single Dropdown.
 *
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

    /** @returns {boolean} whether there are any cog or print items to display */
    get hasItems() {
        return this.cogItems.length || this.props.items.print?.length;
    }

    /**
     * Collect visible items from the cogMenu registry.
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
     * >} merged cog + action items, sorted by group
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
