/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { cloneContentEls } from "@website/js/utils";

export class EmbedCode extends Interaction {
    static selector = ".s_embed_code";

    setup() {
        this.embedCodeEl = this.el.querySelector(".s_embed_code_embedded");
    }

    destroy() {
        const templateContent = this.el.querySelector(
            "template.s_embed_code_saved",
        ).content;
        this.embedCodeEl.replaceChildren(cloneContentEls(templateContent));
    }
}

registry.category("public.interactions").add("website.embed_code", EmbedCode);
