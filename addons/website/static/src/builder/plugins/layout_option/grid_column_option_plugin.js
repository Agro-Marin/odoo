/** @odoo-module native */
import { StyleAction } from "@html_builder/core/core_builder_action_plugin";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { GRID_COLUMNS } from "@website/builder/option_sequence";

import { GridColumnsOption } from "./grid_column_option.js";

const log = makeLogger("website.builder.plugin.grid_columns_option");

export class GridColumnsOptionPlugin extends Plugin {
    static id = "GridColumnsOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(GRID_COLUMNS, GridColumnsOption)],
        builder_actions: {
            SetGridColumnsPaddingAction,
        },
        system_classes: ["o_we_padding_highlight"],
    };
}

registry
    .category("website-plugins")
    .add(GridColumnsOptionPlugin.id, GridColumnsOptionPlugin);

const removePaddingPreview = (event) => {
    const editingElement = event.target;
    editingElement.classList.remove("o_we_padding_highlight");
    editingElement.removeEventListener("animationend", removePaddingPreview);
};
export class SetGridColumnsPaddingAction extends StyleAction {
    static id = "setGridColumnsPadding";
    apply(...args) {
        const { editingElement } = args[0];
        log.pipeline("SetGridColumnsPaddingAction apply", () => ({
            className: editingElement.className,
            isPreviewing: args[0].isPreviewing,
        }));
        removePaddingPreview({ target: editingElement });
        super.apply(...args);
        editingElement.classList.add("o_we_padding_highlight");
        editingElement.addEventListener("animationend", removePaddingPreview);
    }
}
