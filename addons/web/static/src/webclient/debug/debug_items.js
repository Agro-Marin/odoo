// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

import { openUnitTests, UNIT_TESTS_URL, unitTestsLabel } from "./debug_affordances.js";
import { FieldWidgetsDialog } from "./field_widgets_dialog.js";

/**
 * @returns {Object}
 */
function runUnitTestsItem() {
    return {
        type: "item",
        description: unitTestsLabel(),
        href: UNIT_TESTS_URL,
        callback: openUnitTests,
        sequence: 450,
        section: "testing",
    };
}

/**
 * @param {{ env: Object }} params
 * @returns {Object}
 */
export function openViewItem({ env }) {
    async function onSelected(records) {
        const views = await env.services.orm.searchRead(
            "ir.ui.view",
            [["id", "=", records[0]]],
            ["name", "model", "type"],
            { limit: 1 },
        );
        const view = views[0];
        env.services.action.doAction({
            type: "ir.actions.act_window",
            name: view.name,
            res_model: view.model,
            views: [[view.id, view.type]],
        });
    }

    return {
        type: "item",
        description: _t("Open View"),
        callback: () => {
            env.services.dialog.add(SelectCreateDialog, {
                resModel: "ir.ui.view",
                title: _t("Select a view"),
                multiSelect: false,
                domain: [
                    ["type", "!=", "qweb"],
                    ["type", "!=", "search"],
                ],
                onSelected,
            });
        },
        sequence: 540,
        section: "tools",
    };
}

/**
 * @param {{ env: Object }} params
 * @returns {Object}
 */
function inspectFieldWidgetsItem({ env }) {
    return {
        type: "item",
        description: _t("Inspect Field Widgets"),
        callback: () => env.services.dialog.add(FieldWidgetsDialog),
        sequence: 545,
        section: "tools",
    };
}

registry
    .category("debug")
    .category("default")
    .add("runUnitTestsItem", /** @type {any} */ (runUnitTestsItem))
    .add("openViewItem", /** @type {any} */ (openViewItem))
    .add("inspectFieldWidgetsItem", /** @type {any} */ (inspectFieldWidgetsItem));
