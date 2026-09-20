/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { FloatingBlocks } from "@website/snippets/s_floating_blocks/floating_blocks";

const log = makeLogger("website.snippet.s_floating_blocks.edit");

const FloatingBlocksEdit = (I) =>
    class extends I {
        dynamicContent = {
            ...this.dynamicContent,
            ".s_floating_blocks_alert_empty": {
                "t-on-click": this.onAddCard.bind(this),
            },
        };
        isImpactedBy(el) {
            return (
                this.el.contains(el) &&
                el.matches(".s_floating_blocks_block, .s_floating_blocks_wrapper")
            );
        }
        shouldStop() {
            return true;
        }
        start() {
            log.lifecycle("start: rendering empty-alert template", () => ({
                blocks: this.el.querySelectorAll(".s_floating_blocks_block").length,
            }));
            this.renderAt(
                "website.s_floating_blocks.alert.empty",
                {},
                this.el.querySelector(".s_floating_blocks_wrapper"),
            );
            super.start();
        }
        onAddCard() {
            const applySpec = { editingElement: this.el };
            log.pipeline("onAddCard: applying addFloatingBlockCard");
            this.services["website_edit"].applyAction(
                "addFloatingBlockCard",
                applySpec,
            );
        }
    };

registry.category("public.interactions.edit").add("website.floating_blocks", {
    Interaction: FloatingBlocks,
    mixin: FloatingBlocksEdit,
});
