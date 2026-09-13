/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import {
    resizeGrid,
    setElementToMaxZindex,
} from "@html_builder/utils/grid_layout_utils";
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { onceAllImagesLoaded } from "@website/utils/images";

const log = makeLogger("website.builder.plugin.add_element_option");

/**
 * @typedef { Object } AddElementOptionShared
 * @property { AddElementOptionPlugin['addGridElement'] } addGridElement
 */

export class AddElementOptionPlugin extends Plugin {
    static id = "addElementOption";
    static dependencies = ["builderOptions"];
    static shared = ["addGridElement"];
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_actions: {
            AddGridElementAction,
        },
    };

    /**
     * @param {HTMLElement} rowEl
     * @param {HTMLElement} contentEl
     * @param {Number} columnSpan
     * @param {Number} rowSpan
     * @param {Array<String>} [extraClasses = []]
     */
    addGridElement(rowEl, contentEl, columnSpan, rowSpan, extraClasses = []) {
        const currentTime = new Date().getTime();
        if (this.lastAddTime && (currentTime - this.lastAddTime) / 1000 < 15) {
            log.logic("addGridElement cascade: added within 15s of previous", () => ({
                lastStartPosition: [...this.lastStartPosition],
            }));
            this.lastStartPosition = [
                this.lastStartPosition[0] + 1,
                this.lastStartPosition[1] + 1,
            ];
        } else {
            log.logic("addGridElement reset start position");
            this.lastStartPosition = [1, 1];
        }
        this.lastAddTime = currentTime;

        const newColumnEl = document.createElement("div");
        newColumnEl.classList.add("o_grid_item", ...extraClasses);
        newColumnEl.classList.add(
            `g-col-lg-${columnSpan}`,
            `col-lg-${columnSpan}`,
            `g-height-${rowSpan}`,
        );
        newColumnEl.appendChild(contentEl);

        const rowStart = this.lastStartPosition[0];
        let columnStart = this.lastStartPosition[1];
        if (columnStart + columnSpan > 13) {
            log.logic("addGridElement column overflow: wrap to first column", {
                columnStart,
                columnSpan,
            });
            columnStart = 1;
            this.lastStartPosition[1] = columnStart;
        }
        newColumnEl.style.gridArea = `
            ${rowStart} / ${columnStart} / ${rowStart + rowSpan} / ${columnStart + columnSpan}
        `;

        log.pipeline("addGridElement insert grid item", () => ({
            tagName: contentEl.tagName,
            rowStart,
            columnStart,
            columnSpan,
            rowSpan,
            items: rowEl.children.length,
        }));
        setElementToMaxZindex(newColumnEl, rowEl);

        rowEl.appendChild(newColumnEl);
        resizeGrid(rowEl);

        const newColumnPosition = newColumnEl.getBoundingClientRect();
        const middleX = (newColumnPosition.left + newColumnPosition.right) / 2;
        const middleY = (newColumnPosition.top + newColumnPosition.bottom) / 2;
        const sameCoordinatesEl = this.document.elementFromPoint(middleX, middleY);
        if (!sameCoordinatesEl || !newColumnEl.contains(sameCoordinatesEl)) {
            log.logic("addGridElement new item hidden: scroll into view");
            newColumnEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        this.dependencies.builderOptions.setNextTarget(newColumnEl);
    }
}

export class AddGridElementAction extends BuilderAction {
    static id = "addGridElement";
    static dependencies = ["addElementOption", "media"];

    setup() {
        this.canTimeout = false;
    }

    async apply({ editingElement: rowEl, params: { mainParam: elementType } }) {
        log.logic("AddGridElementAction apply", { elementType });
        if (elementType === "image") {
            let imageEl;
            const endMediaDialog = log.perf("AddGridElementAction media dialog");
            await this.dependencies.media.openMediaDialog({
                onlyImages: true,
                noDocuments: true,
                save: (selectedImageEl) => (imageEl = selectedImageEl),
            });
            endMediaDialog(() => ({ selected: !!imageEl }));
            if (!imageEl) {
                log.logic("AddGridElementAction skip: no image selected");
                return;
            }
            const endImagesLoaded = log.perf("AddGridElementAction wait image load");
            await onceAllImagesLoaded(imageEl);
            endImagesLoaded();
            this.dependencies.addElementOption.addGridElement(rowEl, imageEl, 6, 6, [
                "o_grid_item_image",
            ]);
        } else if (elementType === "text") {
            const pEl = document.createElement("p");
            pEl.textContent = _t("Write something...");
            this.dependencies.addElementOption.addGridElement(rowEl, pEl, 4, 2);
        } else if (elementType === "button") {
            const aEl = document.createElement("a");
            aEl.href = "#";
            aEl.classList.add("mb-2", "btn", "btn-primary");
            aEl.textContent = _t("Button");
            this.dependencies.addElementOption.addGridElement(rowEl, aEl, 2, 1);
        }
    }
}

registry
    .category("website-plugins")
    .add(AddElementOptionPlugin.id, AddElementOptionPlugin);
