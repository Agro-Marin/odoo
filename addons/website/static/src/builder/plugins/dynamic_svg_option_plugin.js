/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { DYNAMIC_SVG } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { DEFAULT_PALETTE } from "@html_editor/utils/color";
import { getCSSVariableValue, getHtmlStyle } from "@html_editor/utils/formatting";
import { loadImage } from "@html_editor/utils/image_processing";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { normalizeCSSColor } from "@web/core/utils/format/colors";

import { DynamicSvgOption } from "./dynamic_svg_option.js";

const log = makeLogger("website.builder.plugin.dynamic_svg_option");

class DynamicSvgOptionPlugin extends Plugin {
    static id = "DynamicSvgOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [withSequence(DYNAMIC_SVG, DynamicSvgOption)],
        builder_actions: {
            SvgColorAction,
        },
    };
}

export class SvgColorAction extends BuilderAction {
    static id = "svgColor";
    getValue({ editingElement: imgEl, params: { mainParam: colorName } }) {
        const searchParams = new URL(imgEl.src, window.location.origin).searchParams;
        const color = searchParams.get(colorName);
        return /^o-color-[1-5]$/.test(color)
            ? getCSSVariableValue(color, getHtmlStyle(this.document))
            : normalizeCSSColor(color);
    }
    colorToSearchParams(color) {
        const cssVarMatch = color.match(/var\(--(.+)\)/);
        if (cssVarMatch === null) {
            return normalizeCSSColor(color);
        }
        if (/^o-color-[1-5]$/.test(cssVarMatch[1])) {
            return cssVarMatch[1];
        }
        return getCSSVariableValue(cssVarMatch[1], getHtmlStyle(this.document));
    }
    async load({
        editingElement: imgEl,
        params: { mainParam: colorName },
        value: color,
    }) {
        const newURL = new URL(imgEl.src, window.location.origin);
        let colorValue = color ? this.colorToSearchParams(color) : "";
        if (!colorValue) {
            log.logic("SvgColorAction load fallback: theme or default palette color", {
                colorName,
                color,
            });
            const colorId = colorName.slice(1);
            colorValue =
                getCSSVariableValue(
                    `o-color-${colorId}`,
                    getHtmlStyle(this.document),
                ) || DEFAULT_PALETTE[colorId];
        }
        newURL.searchParams.set(colorName, colorValue);
        const src = newURL.pathname + newURL.search;
        const endLoadImage = log.perf("SvgColorAction load image", { colorName, src });
        await loadImage(src);
        endLoadImage();
        return src;
    }
    apply({
        editingElement: imgEl,
        params: { mainParam: colorName },
        value: color,
        loadResult: newSrc,
    }) {
        log.pipeline("SvgColorAction apply", { colorName, color, newSrc });
        imgEl.setAttribute("src", newSrc);
    }
}

registry
    .category("website-plugins")
    .add(DynamicSvgOptionPlugin.id, DynamicSvgOptionPlugin);
