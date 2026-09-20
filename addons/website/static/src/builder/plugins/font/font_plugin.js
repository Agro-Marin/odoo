/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { getCSSVariableValue, getHtmlStyle } from "@html_editor/utils/formatting";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

import { showAddFontDialog } from "./add_font_dialog.js";

const log = makeLogger("website.builder.plugin.website_font");

/**
 * @typedef { Object } WebsiteFontShared
 * @property { WebsiteFontPlugin['addFont'] } addFont
 * @property { WebsiteFontPlugin['deleteFont'] } deleteFont
 */

class WebsiteFontPlugin extends Plugin {
    static id = "websiteFont";
    static shared = ["addFont", "deleteFont"];
    static dependencies = ["savePlugin", "builderFont", "customizeWebsite"];

    async addFont(variable) {
        const endFontsData = log.perf("addFont getFontsData", { variable });
        const fontsData = await this.dependencies.builderFont.getFontsData();
        endFontsData();
        log.lifecycle("addFont open AddFontDialog", () => ({
            variable,
            allFonts: fontsData.allFonts?.length,
        }));
        showAddFontDialog(
            this.services.dialog,
            fontsData,
            variable,
            this.customizeFonts.bind(this),
            this.config.reloadEditor,
        );
    }
    async customizeFonts({
        values = {},
        googleFonts,
        googleLocalFonts,
        uploadedLocalFonts,
    }) {
        if (googleFonts.length) {
            values["google-fonts"] = "('" + googleFonts.join("', '") + "')";
        } else {
            values["google-fonts"] = "null";
        }
        if (googleLocalFonts.length) {
            values["google-local-fonts"] = "(" + googleLocalFonts.join(", ") + ")";
        } else {
            values["google-local-fonts"] = "null";
        }
        if (uploadedLocalFonts.length) {
            values["uploaded-local-fonts"] = "(" + uploadedLocalFonts.join(", ") + ")";
        } else {
            values["uploaded-local-fonts"] = "null";
        }
        log.pipeline("customizeFonts", () => ({
            values: Object.keys(values),
            googleFonts: googleFonts.length,
            googleLocalFonts: googleLocalFonts.length,
            uploadedLocalFonts: uploadedLocalFonts.length,
        }));
        const endFontsCusto = log.perf("customizeFonts makeSCSSCusto");
        await this.dependencies.customizeWebsite.makeSCSSCusto(
            "/website/static/src/scss/options/user_values.scss",
            values,
        );
        endFontsCusto();
        this.dependencies.builderFont.getFontsCache().invalidate();
        const endFontsSave = log.perf("customizeFonts save");
        await this.dependencies.savePlugin.save();
        endFontsSave();
    }
    async deleteFont(font) {
        const endDeleteFontsData = log.perf("deleteFont getFontsData");
        const { googleFonts, googleLocalFonts, uploadedLocalFonts } =
            await this.dependencies.builderFont.getFontsData();
        endDeleteFontsData();
        const values = {};

        const fontIndex = font.indexForType;
        const localFont = font.type;
        let fontName;
        log.logic("deleteFont", () => ({ type: localFont, fontIndex }));
        if (localFont === "uploaded") {
            const font = uploadedLocalFonts[fontIndex].split(":");
            fontName = font[0].substring(1, font[0].length - 1);
            values["delete-font-attachment-id"] = font[1];
            uploadedLocalFonts.splice(fontIndex, 1);
        } else if (localFont === "google") {
            const googleFont = googleLocalFonts[fontIndex].split(":");
            fontName = googleFont[0].substring(1, googleFont[0].length - 1);
            values["delete-font-attachment-id"] = googleFont[1];
            googleLocalFonts.splice(fontIndex, 1);
        } else {
            fontName = googleFonts[fontIndex];
            googleFonts.splice(fontIndex, 1);
        }

        const style = getHtmlStyle(this.document);
        this.getResource("fontCssVariables").forEach((variable) => {
            const value = getCSSVariableValue(variable, style);
            if (value.substring(1, value.length - 1) === fontName) {
                values[variable] = "null";
            }
        });
        log.pipeline("deleteFont reset variables", () => ({
            fontName,
            variables: Object.keys(values),
        }));
        await this.customizeFonts({
            values: values,
            googleFonts: googleFonts,
            googleLocalFonts: googleLocalFonts,
            uploadedLocalFonts: uploadedLocalFonts,
        });
        log.pipeline("deleteFont reloadEditor", () => ({ fontName }));
        this.config.reloadEditor();
    }
}
registry.category("website-plugins").add(WebsiteFontPlugin.id, WebsiteFontPlugin);
