/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { getRow } from "@html_builder/utils/column_layout_utils";
import {
    convertToNormalColumn,
    reloadLazyImages,
    toggleGridMode,
} from "@html_builder/utils/grid_layout_utils";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { LAYOUT, LAYOUT_GRID } from "@website/builder/option_sequence";

import { LayoutGridOption, LayoutOption } from "./layout_option.js";

const log = makeLogger("website.builder.plugin.layout_option");

class LayoutOptionPlugin extends Plugin {
    static id = "LayoutOption";
    static dependencies = ["clone", "selection"];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [
            withSequence(LAYOUT, LayoutOption),
            withSequence(LAYOUT_GRID, LayoutGridOption),
        ],
        on_cloned_handlers: this.onCloned.bind(this),
        builder_actions: {
            SetGridLayoutAction,
            SetColumnLayoutAction,
        },
    };
    onCloned({ cloneEl }) {
        const cloneElClassList = cloneEl.classList;
        const offsetClasses = [...cloneElClassList].filter((cls) =>
            cls.match(/^offset-(lg-)?([0-9]{1,2})$/),
        );
        log.pipeline("onCloned remove offset classes", { offsetClasses });
        cloneElClassList.remove(...offsetClasses);
    }
}

const isGrid = (el) => {
    const rowEl = getRow(el);
    return !!(rowEl && rowEl.classList.contains("o_grid_mode"));
};
export class SetGridLayoutAction extends BuilderAction {
    static id = "setGridLayout";
    static dependencies = ["selection"];
    apply({ editingElement }) {
        if (isGrid(editingElement)) {
            log.logic("SetGridLayoutAction apply skip: already grid");
            return;
        }
        log.pipeline("SetGridLayoutAction apply toggle grid mode", () => ({
            columns: getRow(editingElement)?.children.length,
        }));
        toggleGridMode(
            editingElement,
            this.dependencies.selection.preserveSelection,
            this.config.mobileBreakpoint,
        );
    }
    isApplied({ editingElement }) {
        return isGrid(editingElement);
    }
}
export class SetColumnLayoutAction extends BuilderAction {
    static id = "setColumnLayout";
    apply({ editingElement }) {
        const rowEl = getRow(editingElement);
        if (!isGrid(editingElement)) {
            log.logic("SetColumnLayoutAction apply skip: not grid");
            return;
        }

        rowEl.classList.remove("o_grid_mode");
        const columnEls = rowEl.children;
        log.pipeline("SetColumnLayoutAction apply convert columns", () => ({
            count: columnEls.length,
        }));

        for (const columnEl of columnEls) {
            reloadLazyImages(columnEl);
            convertToNormalColumn(columnEl, this.config.mobileBreakpoint);
        }
        delete rowEl.dataset.rowCount;
        rowEl.style.removeProperty("--grid-item-padding-x");
        rowEl.style.removeProperty("--grid-item-padding-y");
        rowEl.style.removeProperty("gap");
    }
    isApplied({ editingElement }) {
        return !isGrid(editingElement);
    }
}
registry.category("website-plugins").add(LayoutOptionPlugin.id, LayoutOptionPlugin);
