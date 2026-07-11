// @ts-check
/** @odoo-module native */

/** @module @web/views/widgets/attach_document/attach_document - Widget button that uploads files as ir.attachment records and optionally calls a model action */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { checkFileSize } from "@web/core/utils/files";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class AttachDocumentWidget extends Component {
    static template = "web.AttachDocument";
    static props = {
        ...standardWidgetProps,
        string: { type: String },
        action: { type: String, optional: true },
        highlight: { type: Boolean },
    };

    setup() {
        // Uploads go through a *detached* <input> whose change handler can fire
        // after the component is destroyed (e.g. a statusbar overflow dropdown
        // closing on click). useService() proxies would throw "Component is
        // destroyed" in that window, so use the raw env services instead.
        // eslint-disable-next-line no-restricted-syntax -- see comment above: raw services outlive the component
        this.http = this.env.services.http;
        // eslint-disable-next-line no-restricted-syntax -- see comment above: raw services outlive the component
        this.notification = this.env.services.notification;
        // eslint-disable-next-line no-restricted-syntax -- see comment above: raw services outlive the component
        this.orm = this.env.services.orm;
        this.fileInput = document.createElement("input");
        this.fileInput.type = "file";
        this.fileInput.accept = "*";
        this.fileInput.multiple = true;
        this.fileInput.onchange = this.onInputChange.bind(this);
    }

    /** Validate file sizes and upload selected files to the server. */
    async onInputChange() {
        const ufile = [...this.fileInput.files];
        for (const file of ufile) {
            if (!checkFileSize(file.size, this.notification)) {
                return null;
            }
        }
        const fileData = await this.http.post(
            "/web/binary/upload_attachment",
            {
                csrf_token: odoo.csrf_token,
                ufile: ufile,
                model: this.props.record.resModel,
                id: this.props.record.resId,
            },
            "text",
        );
        const parsedFileData = JSON.parse(fileData);
        if (parsedFileData.error) {
            throw new Error(parsedFileData.error);
        }
        await this.onFileUploaded(parsedFileData);
    }

    /** Save the record first, then open the native file picker. */
    async triggerUpload() {
        if (await this.beforeOpen()) {
            // Reset so re-selecting the same file still fires "change".
            this.fileInput.value = "";
            this.fileInput.click();
        }
    }

    /**
     * After upload, optionally call the configured model action with the new attachment IDs.
     * @param {Array<{id: number}>} files - server response with created attachment records
     */
    async onFileUploaded(files) {
        const { action, record } = this.props;
        if (action) {
            const { resId, resModel } = record;
            await this.orm.call(resModel, action, [resId], {
                attachment_ids: files.map((file) => file.id),
            });
            await record.load();
        }
    }

    /** @returns {Promise<boolean>} save the record before opening the file picker */
    beforeOpen() {
        return this.props.record.save();
    }
}

export const attachDocumentWidget = {
    component: AttachDocumentWidget,
    extractProps: ({ attrs }) => {
        const { action, highlight, string } = attrs;
        return {
            action,
            highlight: !!highlight,
            string,
        };
    },
};

registry.category("view_widgets").add("attach_document", attachDocumentWidget);
