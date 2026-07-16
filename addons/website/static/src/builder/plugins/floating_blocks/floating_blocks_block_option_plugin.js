/** @odoo-module native */
import { BEGIN } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";
import { LAYOUT_GRID } from "@website/builder/option_sequence";

import { FloatingBlocksBlockMobileOption } from "./floating_blocks_block_mobile_option.js";
import { FloatingBlocksBlockOption } from "./floating_blocks_block_option.js";

class FloatingBlocksBlockOptionPlugin extends Plugin {
    static id = "floatingBlocksBlockOptionPlugin";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [
            withSequence(BEGIN, FloatingBlocksBlockMobileOption),
            withSequence(LAYOUT_GRID, FloatingBlocksBlockOption),
        ],
        dropzone_selector: [
            // Lock grid-items within their grid
            {
                selector: ".s_floating_blocks_block_grid .o_grid_item",
                dropLockWithin: ".s_floating_blocks_block_grid",
            },
            // Lock block-items within the snippet
            {
                selector: ".s_floating_blocks .s_floating_blocks_block",
                dropLockWithin: ".s_floating_blocks",
                dropNear: ".s_floating_blocks .s_floating_blocks_block",
            },
        ],
    };
}

registry
    .category("website-plugins")
    .add(FloatingBlocksBlockOptionPlugin.id, FloatingBlocksBlockOptionPlugin);
