/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.floating_blocks_block_mobile_option");

export class FloatingBlocksBlockMobileOption extends BaseOptionComponent {
    static template = "website.FloatingBlocksBlockMobileOption";
    static selector = ".s_floating_blocks .s_floating_blocks_block";
    static applyTo = ".container-fluid";
    setup() {
        super.setup();
        useLifecycleLog(log);
        this.state = useDomState((editingElement) => ({
            isMobileView: this.env.editor.config.isMobileView(editingElement),
        }));
    }
}
