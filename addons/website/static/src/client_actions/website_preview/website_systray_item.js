/** @odoo-module native */
import { Component, onWillStart } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";

import { EditInBackendSystrayItem } from "./edit_in_backend.js";
import { EditWebsiteSystrayItem } from "./edit_website_systray_item.js";
import { MobilePreviewSystrayItem } from "./mobile_preview_systray.js";
import { NewContentSystrayItem } from "./new_content_systray_item.js";
import { PublishSystrayItem } from "./publish_website_systray_item.js";
import { WebsiteSwitcherSystrayItem } from "./website_switcher_systray_item.js";

const log = makeLogger("website.systray.website_systray_item");

export class WebsiteSystrayItem extends Component {
    static template = "website.WebsiteSystrayItem";
    static props = {
        onNewPage: { type: Function },
        onEditPage: { type: Function },
        iframeLoaded: { type: Object },
    };
    static components = {
        MobilePreviewSystrayItem,
        WebsiteSwitcherSystrayItem,
        EditInBackendSystrayItem,
        NewContentSystrayItem,
        EditWebsiteSystrayItem,
        PublishSystrayItem,
    };

    setup() {
        useLifecycleLog(log);
        onWillStart(async () => {
            const endIframe = log.perf("willStart await iframeLoaded");
            this.iframeEl = await this.props.iframeLoaded;
            endIframe();
        });
        this.website = useService("website");
    }

    get hasMultiWebsites() {
        return this.website.websites.length > 1;
    }

    get canPublish() {
        return (
            this.website.currentWebsite &&
            this.website.currentWebsite.metadata.canPublish
        );
    }

    get isRestrictedEditor() {
        return this.website.isRestrictedEditor;
    }

    get hasEditableRecordInBackend() {
        return (
            this.website.currentWebsite &&
            this.website.currentWebsite.metadata.editableInBackend &&
            (!this.website.currentWebsite.metadata.mainObject ||
                !["event.event", "hr.job"].includes(
                    this.website.currentWebsite.metadata.mainObject.model,
                ) ||
                this.website.currentWebsite.metadata.canPublish)
        );
    }

    get canEdit() {
        return (
            this.website.currentWebsite &&
            (this.website.currentWebsite.metadata.editable ||
                this.website.currentWebsite.metadata.translatable)
        );
    }

    get editWebsiteSystrayItemProps() {
        return {
            onNewPage: this.props.onNewPage,
            onEditPage: this.props.onEditPage,
            iframeEl: this.iframeEl,
        };
    }
}
