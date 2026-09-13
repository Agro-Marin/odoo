/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

const log = makeLogger("website.builder.plugin.price_list_plugin");

class PriceListPlugin extends Plugin {
    static id = "priceListPlugin";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_actions: {
            TogglePriceListDescriptionAction,
        },
    };
}

export class TogglePriceListDescriptionAction extends BuilderAction {
    static id = "togglePriceListDescription";
    isApplied({ editingElement, params }) {
        const description = editingElement.querySelector(`.${params.descriptionClass}`);
        return description && !description.classList.contains("d-none");
    }
    apply({ editingElement, params }) {
        const items = editingElement.querySelectorAll(`.${params.itemClass}`);
        log.pipeline("TogglePriceListDescriptionAction apply", () => ({
            items: items.length,
            descriptionClass: params.descriptionClass,
        }));
        for (const item of items) {
            const description = item.querySelector("." + params.descriptionClass);
            if (description) {
                description.classList.remove("d-none");
            } else {
                log.logic(
                    "TogglePriceListDescriptionAction create missing description",
                    () => ({
                        descriptionClass: params.descriptionClass,
                    }),
                );
                const descriptionEl = this.document.createElement("p");
                descriptionEl.classList.add(
                    params.descriptionClass,
                    "d-block",
                    "mt-2",
                    "pe-5",
                    "text-muted",
                );
                if (params.descriptionExtraClass) {
                    descriptionEl.classList.add(params.descriptionExtraClass);
                }
                descriptionEl.textContent = _t("Add a description here");
                item.appendChild(descriptionEl);
            }
        }
    }
    clean({ editingElement, params }) {
        const items = editingElement.querySelectorAll(`.${params.itemClass}`);
        log.pipeline("TogglePriceListDescriptionAction clean", () => ({
            items: items.length,
            descriptionClass: params.descriptionClass,
        }));
        for (const item of items) {
            const description = item.querySelector("." + params.descriptionClass);
            if (description) {
                description.classList.add("d-none");
            }
        }
    }
}

registry.category("website-plugins").add(PriceListPlugin.id, PriceListPlugin);
