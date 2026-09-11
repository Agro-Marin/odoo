/** @odoo-module native */
import { SnippetModel } from "@html_builder/snippets/snippet_service";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";
import { applyTextHighlight } from "@website/js/highlight_utils";

patch(SnippetModel.prototype, {
    /**
     * @override
     */
    updateSnippetContent(snippetEl) {
        super.updateSnippetContent(...arguments);
        for (const textEl of snippetEl?.querySelectorAll(".o_text_highlight") || []) {
            applyTextHighlight(textEl);
        }
    },

    /**
     * @override
     */
    getSnippetLabel(snippetEl, isCustom = false) {
        let label = super.getSnippetLabel(snippetEl);
        if (!label) {
            const contentEl = snippetEl.children[0];
            const parallaxLabel = _t("Parallax");
            if (isCustom) {
                const originalSnippetLabel = this.getOriginalSnippet(
                    contentEl.dataset.snippet,
                )?.label;
                if (originalSnippetLabel && originalSnippetLabel !== parallaxLabel) {
                    label = originalSnippetLabel;
                }
            }
            if (
                !label &&
                (contentEl.matches(".parallax") ||
                    !!contentEl.querySelector(".parallax"))
            ) {
                label = parallaxLabel;
            }
        }
        return label;
    },
});
