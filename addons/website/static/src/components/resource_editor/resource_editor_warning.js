/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";

import { EditHeadBodyDialog } from "../edit_head_body_dialog/edit_head_body_dialog.js";

const log = makeLogger("website.component.resource_editor_warning");

export class ResourceEditorWarningOverlay extends Component {
    static template = "website.ResourceEditorWarningOverlay";
    static props = {};

    setup() {
        useLifecycleLog(log);
        this.website = useService("website");
        this.dialog = useService("dialog");

        const localStorageValue = browser.localStorage.getItem(
            "website.ace.doNotShowWarning",
        );
        log.logic("warning visibility from localStorage", { localStorageValue });
        this.state = useState({
            visible: !localStorageValue || localStorageValue === "false",
        });
    }

    onCloseEditor() {
        log.lifecycle("close resource editor");
        this.website.context.showResourceEditor = false;
    }

    onHideWarning() {
        this.state.visible = false;
    }

    onStopAsking() {
        log.logic("stop asking: persist doNotShowWarning");
        browser.localStorage.setItem("website.ace.doNotShowWarning", "true");
        this.onHideWarning();
    }

    onInjectCode() {
        log.logic("inject code: open EditHeadBodyDialog");
        this.dialog.add(EditHeadBodyDialog);
        this.onCloseEditor();
    }
}
