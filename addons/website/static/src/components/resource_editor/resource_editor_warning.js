/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";

import { EditHeadBodyDialog } from "../edit_head_body_dialog/edit_head_body_dialog.js";

export class ResourceEditorWarningOverlay extends Component {
    static template = "website.ResourceEditorWarningOverlay";
    static props = {};

    setup() {
        this.website = useService("website");
        this.dialog = useService("dialog");

        const localStorageValue = browser.localStorage.getItem(
            "website.ace.doNotShowWarning",
        );
        this.state = useState({
            visible: !localStorageValue || localStorageValue === "false",
        });
    }

    onCloseEditor() {
        this.website.context.showResourceEditor = false;
    }

    onHideWarning() {
        this.state.visible = false;
    }

    onStopAsking() {
        browser.localStorage.setItem("website.ace.doNotShowWarning", "true");
        this.onHideWarning();
    }

    onInjectCode() {
        this.dialog.add(EditHeadBodyDialog);
        this.onCloseEditor();
    }
}
