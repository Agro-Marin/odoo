/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import {
    backgroundImageCssToParts,
    backgroundImagePartsToCss,
} from "@html_editor/utils/image";

/**
 * @typedef { Object } StyleShared
 * @property { StylePlugin['setBackgroundImageUrl'] } setBackgroundImageUrl
 */

export class StylePlugin extends Plugin {
    static id = "style";
    static shared = ["setBackgroundImageUrl"];

    setBackgroundImageUrl(el, value) {
        const parts = backgroundImageCssToParts(el.style["background-image"]);
        if (value) {
            const escapedValue = value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
            parts.url = `url('${escapedValue}')`;
        } else {
            delete parts.url;
        }
        el.style["background-image"] = backgroundImagePartsToCss(parts);
    }
}
