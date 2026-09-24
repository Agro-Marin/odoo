// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { checkFileSize } from "@web/core/utils/files";
import { useServices } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class AttachDocumentWidget extends Component {
    static template = "web.AttachDocument";
    static props = {
        ...standardWidgetProps,
        string: { type: String },
        action: { type: String, optional: true },
        highlight: { type: Boolean },
    };

    /** @type {HTMLInputElement} */
    fileInput;

    setup() {
        this.appServices = useServices();

        this.http = this.appServices.http;

        this.notification = this.appServices.notification;

        this.orm = this.appServices.orm;
        this.fileInput = document.createElement("input");
        this.fileInput.type = "file";
        this.fileInput.accept = "*";
        this.fileInput.multiple = true;
        this.fileInput.onchange = this.onInputChange.bind(this);
    }

    /** @returns {Promise<null | void>} */
    async onInputChange() {
        const ufile = [...(this.fileInput.files ?? [])];
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

    async triggerUpload() {
        if (await this.beforeOpen()) {
            this.fileInput.value = "";
            this.fileInput.click();
        }
    }

    /** @param {Array<{id: number}>} files */
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

    /** @returns {Promise<boolean>} */
    beforeOpen() {
        return this.props.record.save();
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
const attachDocumentWidget = {
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
