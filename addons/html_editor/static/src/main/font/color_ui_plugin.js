/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { Plugin } from "@html_editor/plugin";
import { isTextNode } from "@html_editor/utils/dom_info";
import { closestElement } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";
import { reactive } from "@odoo/owl";
import { _t } from "@web/core/translation";
import {
    isCSSColor,
    normalizeCSSColor,
    RGBA_REGEX,
} from "@web/core/utils/format/colors";

import { ColorSelector } from "./color_selector.js";

const RGBA_OPACITY = 0.6;
const HEX_OPACITY = "99";

/**
 * @typedef { Object } ColorUIShared
 * @property { ColorUIPlugin['getPropsForColorSelector'] } getPropsForColorSelector
 */

export class ColorUIPlugin extends Plugin {
    static id = "colorUi";
    static dependencies = ["color", "history", "selection"];
    static shared = ["getPropsForColorSelector"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        toolbar_items: [
            {
                id: "forecolor",
                groupId: "decoration",
                namespaces: ["compact", "expanded"],
                description: _t("Apply Font Color"),
                Component: ColorSelector,
                props: this.getPropsForColorSelector("foreground"),
                isAvailable: isHtmlContentSupported,
            },
            {
                id: "backcolor",
                groupId: "decoration",
                description: _t("Apply Background Color"),
                Component: ColorSelector,
                props: this.getPropsForColorSelector("background"),
                isAvailable: isHtmlContentSupported,
            },
        ],
        selectionchange_handlers: withSequence(
            100,
            this.updateSelectedColor.bind(this),
        ),
        get_background_color_processors: this.getBackgroundColorProcessor.bind(this),
        apply_background_color_processors:
            this.applyBackgroundColorProcessor.bind(this),
        selected_background_color_providers: withSequence(
            10,
            this.computeBackgroundColorForTextNode.bind(this),
        ),
    };

    setup() {
        this.selectedColors = reactive({ color: "", backgroundColor: "" });
        this.previewableApplyColor = this.dependencies.history.makePreviewableOperation(
            (color, mode, previewMode) =>
                this.dependencies.color.applyColor(color, mode, previewMode),
        );
    }

    /**
     * @param {'foreground'|'background'} type
     */
    getPropsForColorSelector(type) {
        const mode = type === "foreground" ? "color" : "backgroundColor";
        return {
            type,
            mode,

            getUsedCustomColors: () => this.getUsedCustomColors(mode),
            getSelectedColors: () => this.selectedColors,
            applyColor: (color) => this.applyColorCommit({ color, mode }),
            applyColorPreview: (color) => this.applyColorPreview({ color, mode }),
            applyColorResetPreview: this.applyColorResetPreview.bind(this),
            colorPrefix: mode === "color" ? "text-" : "bg-",
            onClose: () => this.dependencies.selection.focusEditable(),
            getTargetedElements: () => {
                const nodes = this.dependencies.selection
                    .getTargetedNodes()
                    .filter(isTextNode);
                return nodes.map((node) => closestElement(node));
            },
        };
    }

    /**
     * @param {Object} param
     * @param {string} param.color
     * @param {string} param.mode
     */
    applyColorCommit({ color, mode }) {
        this.previewableApplyColor.commit(color, mode);
        this.updateSelectedColor();
    }
    /**
     * @param {Object} param
     * @param {string} param.color
     * @param {string} param.mode
     */
    applyColorPreview({ color, mode }) {
        this.previewableApplyColor.preview(color, mode, true);
        this.updateSelectedColor();
    }
    applyColorResetPreview() {
        this.previewableApplyColor.revert();
        this.updateSelectedColor();
    }

    getUsedCustomColors(mode) {
        const allFont = this.editable.querySelectorAll("font");
        const usedCustomColors = new Set();
        for (const font of allFont) {
            if (isCSSColor(font.style[mode])) {
                usedCustomColors.add(normalizeCSSColor(font.style[mode]));
            }
        }
        return usedCustomColors;
    }

    computeBackgroundColorForTextNode() {
        const nodes = this.dependencies.selection.getTargetedNodes().filter(isTextNode);
        if (nodes.length === 0) {
            return;
        }
        const el = closestElement(nodes[0]);
        if (!el) {
            return;
        }

        return this.dependencies.color.getElementColors(el).backgroundColor;
    }

    updateSelectedColor() {
        let backgroundColor;
        for (const provider of this.getResource(
            "selected_background_color_providers",
        )) {
            const providedBackgroundColor = provider();
            if (providedBackgroundColor) {
                backgroundColor = providedBackgroundColor;
                break;
            }
        }

        this.selectedColors.backgroundColor = backgroundColor || "#00000000";

        const nodes = this.dependencies.selection.getTargetedNodes().filter(isTextNode);
        if (nodes.length === 0) {
            this.selectedColors.color = "";
            return;
        }
        const el = closestElement(nodes[0]);
        if (!el) {
            this.selectedColors.color = "";
            return;
        }
        this.selectedColors.color = this.dependencies.color.getElementColors(el).color;
    }

    getBackgroundColorProcessor(backgroundColor) {
        const activeTab = document
            .querySelector(".o_font_color_selector button.active")
            ?.innerHTML.trim();
        if (
            backgroundColor.startsWith("rgba") &&
            (!activeTab || activeTab === "Solid")
        ) {
            const values = backgroundColor.match(RGBA_REGEX) || [];
            const alpha = parseFloat(values.pop());
            if (alpha === RGBA_OPACITY) {
                backgroundColor = `rgb(${values.slice(0, 3).join(", ")})`;
            }
        }
        return backgroundColor;
    }

    applyBackgroundColorProcessor(brackgroundColor) {
        const activeTab = document
            .querySelector(".o_font_color_selector button.active")
            ?.innerHTML.trim();
        if (activeTab === "Solid" && brackgroundColor.startsWith("#")) {
            brackgroundColor += HEX_OPACITY;
        }
        return brackgroundColor;
    }
}
