/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import {
    resizeGrid,
    setElementToMaxZindex,
} from "@html_builder/utils/grid_layout_utils";
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { onceAllImagesLoaded } from "@website/utils/images";

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
            this.lastStartPosition = [
                this.lastStartPosition[0] + 1,
                this.lastStartPosition[1] + 1,
            ];
        } else {
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
            columnStart = 1;
            this.lastStartPosition[1] = columnStart;
        }
        newColumnEl.style.gridArea = `
            ${rowStart} / ${columnStart} / ${rowStart + rowSpan} / ${columnStart + columnSpan}
        `;

        setElementToMaxZindex(newColumnEl, rowEl);

        rowEl.appendChild(newColumnEl);
        resizeGrid(rowEl);

        const newColumnPosition = newColumnEl.getBoundingClientRect();
        const middleX = (newColumnPosition.left + newColumnPosition.right) / 2;
        const middleY = (newColumnPosition.top + newColumnPosition.bottom) / 2;
        const sameCoordinatesEl = this.document.elementFromPoint(middleX, middleY);
        if (!sameCoordinatesEl || !newColumnEl.contains(sameCoordinatesEl)) {
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
        if (elementType === "image") {
            let imageEl;
            await this.dependencies.media.openMediaDialog({
                onlyImages: true,
                noDocuments: true,
                save: (selectedImageEl) => (imageEl = selectedImageEl),
            });
            if (!imageEl) {
                return;
            }
            await onceAllImagesLoaded(imageEl);
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
