/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { EmbedCode } from "@website/snippets/s_embed_code/embed_code";

const log = makeLogger("website.snippet.s_embed_code.edit");

const EmbedCodeEdit = (I) =>
    class extends I {
        start() {
            if (this.embedCodeEl.offsetHeight === 0) {
                log.logic("start: empty embed, inserting placeholder");
                const placeholderEl = document.createElement("div");
                placeholderEl.classList.add(
                    "s_embed_code_placeholder",
                    "alert",
                    "alert-info",
                    "pt16",
                    "pb16",
                );
                placeholderEl.textContent = _t(
                    "Your Embed Code snippet doesn't have anything to display. Click on Edit to modify it.",
                );
                this.embedCodeEl.appendChild(placeholderEl);
            }
        }
        destroy() {}
    };

registry.category("public.interactions.edit").add("website.embed_code", {
    Interaction: EmbedCode,
    mixin: EmbedCodeEdit,
});
