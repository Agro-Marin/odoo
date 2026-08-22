/** @odoo-module native */
import { Component, markup } from "@odoo/owl";
import { FileUploader } from "@web/core/file_upload";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";

export class DocumentFileUploader extends Component {
    static template = "account.DocumentFileUploader";
    static components = {
        FileUploader,
    };
    static props = {
        ...standardWidgetProps,
        record: { type: Object, optional: true },
        slots: { type: Object, optional: true },
        resModel: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.attachmentIdsToProcess = [];
        this.extraContext = this.getExtraContext();
    }

    getExtraContext() {
        return {};
    }

    async onFileUploaded(file) {
        const att_data = {
            name: file.name,
            mimetype: file.type,
            datas: file.data,
        };
        const cleanContext = Object.fromEntries(
            Object.entries(this.env.searchModel.context).filter(
                ([key]) => !key.startsWith("default_"),
            ),
        );
        const [att_id] = await this.orm.create("ir.attachment", [att_data], {
            context: cleanContext,
        });
        this.attachmentIdsToProcess.push(att_id);
    }

    getResModel() {
        return this.props.resModel;
    }

    /**
     * @returns {string}
     */
    getUploadMethod() {
        return "create_document_from_attachment";
    }

    /**
     * @returns {Promise<number[]|string>}
     */
    async getUploadIds() {
        return "";
    }

    async onUploadComplete() {
        const resModal = this.getResModel();
        let action;
        try {
            action = await this.orm.call(
                resModal,
                this.getUploadMethod(),
                [await this.getUploadIds(), this.attachmentIdsToProcess],
                { context: { ...this.extraContext, ...this.env.searchModel.context } },
            );
        } finally {
            this.attachmentIdsToProcess = [];
        }
        if (!action) {
            return;
        }
        if (action.context && action.context.notifications) {
            for (const [file, msg] of Object.entries(action.context.notifications)) {
                this.notification.add(msg, {
                    title: file,
                    type: "info",
                    sticky: true,
                });
            }
            delete action.context.notifications;
        }
        if (action.help?.length) {
            action.help = markup(action.help);
        }
        this.action.doAction(action);
    }
}
