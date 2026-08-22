/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

import { sendFilesToUploadInput } from "../document_file_uploader/upload_input.js";

export class UploadDropZone extends Component {
    static template = "account.UploadDropZone";
    static props = {
        dragging: { type: Boolean, optional: true },
        visible: { type: Boolean, optional: true },
        hideZone: { type: Function, optional: true },
        dragIcon: { type: String, optional: true },
        dragText: { type: String, optional: true },
        dragTitle: { type: String, optional: true },
        dragCompany: { type: String, optional: true },
        dragShowCompany: { type: Boolean, optional: true },
        dropZoneTitle: { type: String, optional: true },
        dropZoneDescription: { type: String, optional: true },
    };
    static defaultProps = {
        hideZone: () => {},
    };

    setup() {
        this.notificationService = useService("notification");
    }

    onDrop(ev) {
        sendFilesToUploadInput(ev.dataTransfer, {
            scopeEl: ev.target.closest(".o_drop_area")?.parentElement,
            notification: this.notificationService,
        });
        this.props.hideZone();
    }
}
