/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { _t } from "@web/core/l10n/translation";

import { VideoSelector } from "./media_dialog/video_selector.js";

export class VideoPlugin extends Plugin {
    static id = "video";
    static defaultConfig = {
        allowVideo: true,
    };
    /** @type {import("plugins").EditorResources} */
    resources = {
        ...(this.config.allowVideo && {
            media_dialog_extra_tabs: {
                id: "VIDEOS",
                title: _t("Videos"),
                Component: this.componentForMediaDialog,
                sequence: 30,
            },
        }),
    };

    get componentForMediaDialog() {
        return VideoSelector;
    }
}
