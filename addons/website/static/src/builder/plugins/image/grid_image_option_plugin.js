/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";
import { GRID_IMAGE } from "@website/builder/option_sequence";

import { GridImageOption } from "./grid_image_option.js";

class GridImageOptionPlugin extends Plugin {
    static id = "gridImageOption";

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(GRID_IMAGE, GridImageOption)],
        builder_actions: {
            SetGridImageModeAction,
        },
    };
}

export class SetGridImageModeAction extends BuilderAction {
    static id = "setGridImageMode";
    apply({ editingElement, value: mode }) {
        const imageGridItemEl = editingElement.closest(".o_grid_item_image");
        if (imageGridItemEl) {
            imageGridItemEl.classList.toggle(
                "o_grid_item_image_contain",
                mode === "contain",
            );
        }
    }
    isApplied({ editingElement, value: mode }) {
        const imageGridItemEl = editingElement.closest(".o_grid_item_image");
        return imageGridItemEl &&
            imageGridItemEl.classList.contains("o_grid_item_image_contain")
            ? mode === "contain"
            : mode === "cover";
    }
}

registry
    .category("website-plugins")
    .add(GridImageOptionPlugin.id, GridImageOptionPlugin);
