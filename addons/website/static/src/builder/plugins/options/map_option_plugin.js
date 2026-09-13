/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { generateGMapLink } from "@website/js/utils";

const log = makeLogger("website.builder.plugin.map_option");

export class MapOption extends BaseOptionComponent {
    static template = "website.mapOption";
    static selector = ".s_map";
}

class MapOptionPlugin extends Plugin {
    static id = "mapOption";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [MapOption],
        so_content_addition_selector: [".s_map"],
        builder_actions: {
            MapUpdateSrcAction,
            MapDescriptionAction,
        },
        keep_overlay_options: (el) => el.matches(".s_map"),
    };
}

export class MapUpdateSrcAction extends BuilderAction {
    static id = "mapUpdateSrc";
    apply({ editingElement }) {
        const embedded = editingElement.querySelector(".s_map_embedded");

        if (editingElement.dataset.mapAddress) {
            const url = generateGMapLink(editingElement.dataset);
            log.logic("MapUpdateSrcAction apply", () => ({
                url,
                changed: url !== embedded.getAttribute("src"),
            }));
            if (url !== embedded.getAttribute("src")) {
                embedded.setAttribute("src", url);
            }
        } else {
            log.logic("MapUpdateSrcAction apply: no address, blank map");
            embedded.setAttribute("src", "about:blank");
        }
        embedded.classList.toggle("d-none", !editingElement.dataset.mapAddress);
        editingElement
            .querySelector(".missing_option_warning")
            .classList.toggle("d-none", !!editingElement.dataset.mapAddress);
    }
}
export class MapDescriptionAction extends BuilderAction {
    static id = "mapDescription";
    isApplied({ editingElement }) {
        return editingElement.querySelector(".description") !== null;
    }
    apply({ editingElement }) {
        log.pipeline("MapDescriptionAction apply");
        editingElement.appendChild(
            document.createRange().createContextualFragment(
                `<div class="description">
                    <strong>${_t("Visit us:")}</strong>
                    ${_t("Our office is open Monday – Friday 8:30 a.m. – 4:00 p.m.")}
                </div>`,
            ),
        );
    }
    clean({ editingElement }) {
        log.pipeline("MapDescriptionAction clean");
        editingElement.querySelector(".description").remove();
    }
}

registry.category("website-plugins").add(MapOptionPlugin.id, MapOptionPlugin);
