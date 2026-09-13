/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { after } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { renderToElement } from "@web/core/utils/render";
import { DEVICE_VISIBILITY } from "@website/builder/option_sequence";

const log = makeLogger("website.builder.plugin.floating_blocks_option_plugin");

export class FloatingBlocksOption extends BaseOptionComponent {
    static template = "website.FloatingBlocksOption";
    static selector = ".s_floating_blocks";
}

export class FloatingBlocksOptionPlugin extends Plugin {
    static id = "floatingBlocksOptionPlugin";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(after(DEVICE_VISIBILITY), FloatingBlocksOption)],
        builder_actions: {
            FloatingBlocksRoundnessAction,
            AddFloatingBlockCardAction,
        },
    };
}

export class FloatingBlocksRoundnessAction extends BuilderAction {
    static id = "floatingBlocksRoundness";
    getValue({ editingElement }) {
        for (let x = 0; x <= 5; x++) {
            if (editingElement.classList.contains(`rounded-${x}`)) {
                return x;
            }
        }
        return 0;
    }
    apply({ editingElement, value }) {
        log.pipeline("FloatingBlocksRoundnessAction apply", { value });
        for (let x = 0; x <= 5; x++) {
            editingElement.classList.remove(`rounded-${x}`);
        }
        editingElement.classList.add(`rounded-${value}`);
    }
}
export class AddFloatingBlockCardAction extends BuilderAction {
    static id = "addFloatingBlockCard";
    static dependencies = ["builderOptions"];
    apply({ editingElement: el }) {
        const endRender = log.perf("AddFloatingBlockCardAction render card");
        const newCardEl = renderToElement("website.s_floating_blocks.new_card");
        const wrapperEl = el.querySelector(".s_floating_blocks_wrapper");
        wrapperEl.appendChild(newCardEl);
        endRender(() => ({ cards: wrapperEl.children.length }));
        newCardEl.scrollIntoView({ behavior: "smooth", block: "center" });
        this.dependencies.builderOptions.setNextTarget(newCardEl);
    }
}

registry
    .category("website-plugins")
    .add(FloatingBlocksOptionPlugin.id, FloatingBlocksOptionPlugin);
