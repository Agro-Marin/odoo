/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";
import { ClassAction } from "@html_builder/core/core_builder_action_plugin";
import { VerticalAlignmentOption } from "@html_builder/plugins/vertical_alignment_option";
import { withSequence } from "@html_editor/utils/resource";
import { VERTICAL_ALIGNMENT } from "@html_builder/utils/option_sequence";

export class VerticalAlignmentOptionPlugin extends Plugin {
    static id = "verticalAlignmentOption";
    /** @type {import("plugins").BuilderResources} */
    resources = {
        builder_options: [withSequence(VERTICAL_ALIGNMENT, VerticalAlignmentOption)],
        builder_actions: {
            SetVerticalAlignmentAction,
        },
    };

    setup() {
        this.upgradeContainers();
    }

    /**
     * The card snippets predate the vertical alignment option, so their cards
     * do not stretch and "Stretch to Equal Height" would do nothing visible on
     * them. Give the markup what the option needs, and stamp the section so
     * the work is done once.
     *
     * TODO: remove once snippets are compared by their data-vxml version.
     */
    upgradeContainers() {
        const snippetEls = this.document.querySelectorAll(
            ".s_cards_soft:not([data-vxml]), .s_cards_grid:not([data-vxml])"
        );
        for (const snippetEl of snippetEls) {
            const isCardsGrid = snippetEl.classList.contains("s_cards_grid");
            for (const cardEl of snippetEl.querySelectorAll(".s_card")) {
                // Cards that had no h-100 were top-aligned in effect; keep that
                // as the explicit starting point instead of silently changing it.
                cardEl.closest(".row")?.classList.add("align-items-start");
                cardEl.classList.add("h-100");
                if (!isCardsGrid) {
                    continue;
                }
                cardEl.closest("[class*='col-']")?.classList.add("d-flex", "flex-column");
                cardEl.querySelector(".o_card_img, img")?.classList.add("object-fit-cover");
            }
            snippetEl.dataset.vxml = "001";
        }
    }
}

export class SetVerticalAlignmentAction extends ClassAction {
    static id = "setVerticalAlignment";
    getPriority({ params: { mainParam: classNames } = { mainParam: "" } }) {
        return classNames === "align-items-stretch" ? 0 : 1;
    }
    isApplied({ params: { mainParam: classNames } }) {
        if (classNames === "align-items-stretch") {
            return true;
        }
        return super.isApplied(...arguments);
    }
}

registry
    .category("builder-plugins")
    .add(VerticalAlignmentOptionPlugin.id, VerticalAlignmentOptionPlugin);
