/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

import { sendFilesToUploadInput } from "../document_file_uploader/upload_input.js";

export class UploadDropZone extends Component {
    static template = "account.UploadDropZone";
    static props = {
        // A drag is in progress somewhere the owner cares about, so every zone it
        // owns offers itself as a target.
        dragging: { type: Boolean, optional: true },
        // The pointer is over THIS zone: it is the one a drop would land in.
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
            // The input beside the zone dropped on carries that card's context;
            // fall back to any in the page. `closest` is optional-chained because
            // a drop can land on a child of the zone.
            scopeEl: ev.target.closest(".o_drop_area")?.parentElement,
            notification: this.notificationService,
        });
        this.props.hideZone();
    }
}
