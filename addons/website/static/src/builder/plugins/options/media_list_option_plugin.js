/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { BEGIN, END } from "@html_builder/utils/option_sequence";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

import { MediaListItemOption } from "./media_list_item_option.js";

const log = makeLogger("website.builder.plugin.media_list_option");

export class MediaListOption extends BaseOptionComponent {
    static template = "website.MediaListOption";
    static selector = ".s_media_list";
}

class MediaListOptionPlugin extends Plugin {
    static id = "mediaListOption";
    mediaListItemOptionSelector = ".s_media_list_item";
    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_options: [
            withSequence(BEGIN, MediaListOption),
            withSequence(END, MediaListItemOption),
        ],
        builder_actions: {
            SetMediaLayoutAction,
        },
        mark_color_level_selector_params: [
            { selector: MediaListItemOption.selector, applyTo: ":scope > .row" },
        ],
    };
}

export class SetMediaLayoutAction extends BuilderAction {
    static id = "setMediaLayout";
    isApplied({ editingElement, value }) {
        const image = editingElement.querySelector(".s_media_list_img_wrapper");
        return image.classList.contains(`col-lg-${value}`);
    }
    apply({ editingElement, value }) {
        log.pipeline("SetMediaLayoutAction apply", () => ({ imageColumns: value }));
        const image = editingElement.querySelector(".s_media_list_img_wrapper");
        const content = editingElement.querySelector(".s_media_list_body");
        image.classList.add(`col-lg-${value}`);
        content.classList.add(`col-lg-${12 - value}`);
    }
    clean({ editingElement, value }) {
        log.pipeline("SetMediaLayoutAction clean", () => ({ imageColumns: value }));
        const image = editingElement.querySelector(".s_media_list_img_wrapper");
        const content = editingElement.querySelector(".s_media_list_body");
        image.classList.remove(`col-lg-${value}`);
        content.classList.remove(`col-lg-${12 - value}`);
    }
}

registry
    .category("website-plugins")
    .add(MediaListOptionPlugin.id, MediaListOptionPlugin);
