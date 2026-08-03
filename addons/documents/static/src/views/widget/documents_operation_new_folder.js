/** @odoo-module native */
import { _t } from "@web/core/translation";
import { registry } from "@web/core/registry";

import { FormViewDialog } from "@web/views/view_dialogs";
import { standardWidgetProps } from "@web/views/widgets";
import { useService } from "@web/core/utils/hooks";

import { Component } from "@odoo/owl";
import { DESTINATION_MAX_LENGTH, truncate } from "@documents/views/widget/utils";

export class DocumentsOperationNewFolder extends Component {
    static template = "documents.DocumentsOperationNewFolder";
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.documentService = useService("document.document");
    }

    async onClick() {
        const currentFolder = this.props.record.data.destination;
        const documents = this.props.record.data.document_ids.records.map((f) => ({
            id: f.resId,
            name: f.data.display_name,
        }));
        const attachmentId = this.props.record.data.attachment_id.id;
        const operation = this.props.record.data.operation;
        this.dialog.add(FormViewDialog, {
            canExpand: false,
            resModel: "documents.document",
            size: "md",
            title: this.buttonLabel,
            context: {
                default_type: "folder",
                default_user_folder_id: currentFolder.toString(),
                ...(currentFolder === "COMPANY" ? { default_access_internal: "edit" } : {}),
                form_view_ref: "documents.document_view_form_new_folder",
            },
            onRecordSaved: (result) => {
                this.documentService.openOperationDialog({
                    documents,
                    attachmentId,
                    operation,
                    // Through the service, not `this.env.searchModel`: this
                    // widget lives inside the operation dialog's own form view,
                    // whose env carries that form's plain SearchModel -- so
                    // `_reloadSearchModel` was not a function there and creating
                    // a folder from the duplicate/move dialog threw on close,
                    // leaving the search panel without the folder it had just
                    // made. `reload()` hands the refresh to the Documents view
                    // that owns the DocumentsSearchModel (see the
                    // `DOCUMENT_RELOAD` bus subscriber in `views/hooks.js`),
                    // which reloads the record list too.
                    onClose: () => this.documentService.reload(),
                    context: {
                        default_destination: result.resId.toString(),
                        default_display_name: result.data.name,
                    },
                });
            },
        });
    }

    get buttonLabel() {
        return _t("Create a folder in %(folder)s", {
            folder: truncate(this.props.record.data.display_name, DESTINATION_MAX_LENGTH),
        });
    }
}

export const documentsOperationNewFolder = {
    component: DocumentsOperationNewFolder,
    fieldDependencies: [
        { name: "attachment_id", type: "many2one" },
        { name: "destination", type: "char" },
        { name: "display_name", type: "char" },
        { name: "document_ids", type: "many2many" },
        { name: "operation", type: "char" },
    ],
};

registry
    .category("view_widgets")
    .add("documents_operation_new_folder", documentsOperationNewFolder);
