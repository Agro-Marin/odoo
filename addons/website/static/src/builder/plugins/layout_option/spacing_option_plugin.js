/** @odoo-module native */
import { StyleAction } from "@html_builder/core/core_builder_action_plugin";
import {
    addBackgroundGrid,
    setElementToMaxZindex,
} from "@html_builder/utils/grid_layout_utils";
import { Plugin } from "@html_editor/plugin";
import { isBlock } from "@html_editor/utils/blocks";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.builder.plugin.spacing_option");

class SpacingOptionPlugin extends Plugin {
    static id = "SpacingOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_actions: {
            SetGridSpacingAction,
        },
        savable_mutation_record_predicates: this.isMutationRecordSavable.bind(this),
        on_cloned_handlers: this.onCloned.bind(this),
        clean_for_save_handlers: this.cleanForSave.bind(this),
    };

    /**
     * @param {import("@html_editor/core/history_plugin").HistoryMutationRecord} record
     */
    isMutationRecordSavable(record) {
        if (record.type === "childList") {
            const node = (record.addedTrees[0] || record.removedTrees[0]).node;
            if (node.matches && node.matches(".o_we_grid_preview") && isBlock(node)) {
                return false;
            }
        }
        if (record.type === "attributes") {
            if (record.target.matches(".o_we_grid_preview")) {
                return false;
            }
        }
        return true;
    }

    removeGridPreviews(el) {
        el.querySelectorAll(".o_we_grid_preview").forEach((gridPreviewEl) =>
            gridPreviewEl.remove(),
        );
    }

    onCloned({ cloneEl }) {
        log.pipeline("onCloned remove grid previews", () => ({
            count: cloneEl.querySelectorAll(".o_we_grid_preview").length,
        }));
        this.removeGridPreviews(cloneEl);
    }

    cleanForSave({ root }) {
        log.pipeline("cleanForSave remove grid previews", () => ({
            count: root.querySelectorAll(".o_we_grid_preview").length,
        }));
        this.removeGridPreviews(root);
    }
}

registry.category("website-plugins").add(SpacingOptionPlugin.id, SpacingOptionPlugin);

export class SetGridSpacingAction extends StyleAction {
    static id = "setGridSpacing";
    apply({ editingElement: rowEl }) {
        let gridPreviewEl = rowEl.querySelector(".o_we_grid_preview");
        if (gridPreviewEl) {
            log.logic("SetGridSpacingAction apply: replacing pending grid preview");
            gridPreviewEl.remove();
        }
        log.pipeline("SetGridSpacingAction apply", () => ({
            className: rowEl.className,
        }));
        super.apply(...arguments);
        gridPreviewEl = addBackgroundGrid(rowEl, 0);
        gridPreviewEl.classList.add("o_we_grid_preview");
        setElementToMaxZindex(gridPreviewEl, rowEl);
        gridPreviewEl.addEventListener("animationend", () => gridPreviewEl.remove());
    }
}
