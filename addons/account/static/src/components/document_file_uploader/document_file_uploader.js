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

    // To pass extra context while creating record
    getExtraContext() {
        return {};
    }

    async onFileUploaded(file) {
        const att_data = {
            name: file.name,
            mimetype: file.type,
            datas: file.data,
        };
        // clean the context to ensure the `create` call doesn't fail from unknown `default_*` context
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

    // To define a specific resModel from another model
    getResModel() {
        return this.props.resModel;
    }

    /**
     * Model method that turns the uploaded attachments into a document.
     *
     * Overridable so a subclass does not have to reimplement the whole upload
     * flow — the context cleaning, per-file notifications and markup handling
     * below are the same wherever the documents come from.
     *
     * @returns {string}
     */
    getUploadMethod() {
        return "create_document_from_attachment";
    }

    /**
     * Recordset ids the upload method is bound to, i.e. the `self` it runs on.
     *
     * The base uploads against no records; a subclass that creates documents
     * *from* existing records (purchase orders, say) returns their ids.
     *
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
            // ensures attachments are cleared on success as well as on error
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
