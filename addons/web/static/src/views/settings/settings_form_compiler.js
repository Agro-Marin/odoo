// @ts-check
/** @odoo-module native */

import { append, createElement } from "@web/core/utils/dom/xml";
import { FormCompiler } from "@web/views/form/form_compiler";
import { isTextNode } from "@web/views/view_compiler";
import { toStringExpression } from "@web/views/view_utils";
export class SettingsFormCompiler extends FormCompiler {
    setup() {
        super.setup();
        /** @type {any} */ (this).compilers.push(
            { selector: "app", fn: this.compileApp },
            { selector: "block", fn: this.compileBlock },
        );
    }

    compileForm(el, params) {
        const settingsPage = createElement("SettingsPage");
        settingsPage.setAttribute(
            "slots",
            "{NoContentHelper:__comp__.props.slots.NoContentHelper}",
        );
        settingsPage.setAttribute("initialTab", "__comp__.props.initialApp");
        settingsPage.setAttribute("t-slot-scope", "settings");

        params.modules = [];
        params.anchors = [];

        // @ts-ignore — super.compileForm is on the parent's prototype but not in the strict typedef
        const res = super.compileForm(el, params);
        res.classList.remove("o_form_nosheet");

        settingsPage.setAttribute("modules", JSON.stringify(params.modules));

        while (res.firstChild) {
            append(settingsPage, res.firstChild);
        }

        settingsPage.setAttribute("anchors", JSON.stringify(params.anchors));

        append(res, settingsPage);

        return res;
    }

    compileApp(el, params) {
        if (el.getAttribute("notApp") === "1") {
            return;
        }
        const module = {
            key: el.getAttribute("name"),
            string: el.getAttribute("string"),
            imgurl:
                el.getAttribute("logo") ||
                `/${el.getAttribute("name")}/static/description/icon.png`,
        };
        params.modules.push(module);
        const settingsApp = createElement("SettingsApp", {
            key: toStringExpression(module.key),
            string: toStringExpression(module.string || ""),
            imgurl: toStringExpression(module.imgurl),
            selectedTab: "settings.selectedTab",
        });

        for (const child of el.children) {
            append(settingsApp, this.compileNode(child, params));
        }

        params.anchors.push(
            ...[...settingsApp.querySelectorAll("SearchableSetting")]
                .filter((s) => s.id)
                .map((s) => ({
                    app: module.key,
                    settingId: s.id.replaceAll("`", ""),
                })),
        );
        return settingsApp;
    }

    compileBlock(el, params) {
        const settingsContainer = createElement("SettingsBlock", {
            title: toStringExpression(el.getAttribute("title") || ""),
            tip: toStringExpression(el.getAttribute("help") || ""),
        });
        for (const child of el.children) {
            append(settingsContainer, this.compileNode(child, params));
        }
        return settingsContainer;
    }

    compileSetting(el, params) {
        params.componentName =
            el.getAttribute("type") === "header"
                ? "SettingHeader"
                : "SearchableSetting";
        // @ts-ignore — super.compileSetting is on the parent's prototype but not in the strict typedef
        const res = super.compileSetting(el, params);
        return res;
    }

    compileNode(node, params, evalInvisible) {
        if (isTextNode(node)) {
            if (node.textContent.trim()) {
                return createElement("HighlightText", {
                    originalText: toStringExpression(node.textContent),
                });
            }
        }
        // @ts-ignore — super.compileNode is on the parent's prototype but not in the strict typedef
        return super.compileNode(node, params, evalInvisible);
    }

    compileButton(el, params) {
        // @ts-ignore — super.compileButton is on the parent's prototype but not in the strict typedef
        const res = super.compileButton(el, params);
        if (res.hasAttribute("string") && !res.children.length) {
            const contentSlot = createElement("t");
            contentSlot.setAttribute("t-set-slot", "contents");
            const content = createElement("HighlightText", {
                originalText: res.getAttribute("string"),
            });
            append(contentSlot, content);
            append(res, contentSlot);
        }
        return res;
    }
}
