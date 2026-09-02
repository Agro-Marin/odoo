/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { Popover } from "@web/libs/bootstrap";
import { Interaction } from "@web/public/interaction";

export class EmbedShare extends Interaction {
    static selector = ".oe_slide_js_embed_code_widget";
    dynamicContent = {
        ".o_embed_clipboard_button": { "t-on-click.prevent.withTarget": this.onClick },
    };

    /**
     * @param {MouseEvent} ev
     * @param {HTMLElement} currentTargetEl
     */
    async onClick(ev, currentTargetEl) {
        const embedEl = document.querySelector(
            "#wslides_share_embed_id_" + currentTargetEl.id.split("id_")[1],
        );
        await this.waitFor(browser.navigator.clipboard.writeText(embedEl.value || ""));
        const bsPopover = Popover.getOrCreateInstance(currentTargetEl, {
            title: "Copied!",
            trigger: "manual",
            placement: "bottom",
        });
        this.registerCleanup(() => bsPopover.dispose());
        bsPopover.show();
        this.waitForTimeout(() => bsPopover.hide(), 800);
    }
}

registry.category("public.interactions").add("website_slides.embed_share", EmbedShare);
