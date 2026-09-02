/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { BLOCK_ALIGN } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { registry } from "@web/core/registry";

class BlockAlignmentOptionPlugin extends Plugin {
    static id = "blockAlignmentOption";
    /** @type {import("plugins").BuilderResources} */
    resources = {
        builder_options: [withSequence(BLOCK_ALIGN, BlockAlignmentOption)],
    };
}

export class BlockAlignmentOption extends BaseOptionComponent {
    static template = "html_builder.BlockAlignmentOption";
    static selector = ".s_alert, .s_blockquote, .s_text_highlight";
}

registry
    .category("builder-plugins")
    .add(BlockAlignmentOptionPlugin.id, BlockAlignmentOptionPlugin);
